
import uvicorn
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware 
from psycopg2 import pool
from pymongo import MongoClient
from neo4j import GraphDatabase
import redis.asyncio as redis
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime

POSTGRES_CONN_STRING = "host=localhost port=5432 dbname=compras_db user=postgres password=postgres"
MONGO_CONN_STRING = "mongodb://localhost:27017/"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "testeteste"
REDIS_HOST = "localhost"
REDIS_PORT = 6379


app = FastAPI(
    title="API Completa de Gestão e Recomendação",
    description="Permite gerir clientes, produtos, compras e amizades, e recomenda produtos com base nas compras dos amigos.",
    version="2.0.0"
)

origins = [
    "*", 
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

class ClienteCreateModel(BaseModel):
    cpf: str
    rg: Optional[str] = None
    nome: str
    telefone: str
    email: EmailStr # Alterado para ser obrigatório
    endereco: Optional[str] = None
    dt_nasc: Optional[date] = None

class ProdutoCreateModel(BaseModel):
    idprod: int
    produto: str
    quantidade: int
    preco: float

class AmizadeCreateModel(BaseModel):
    cpf_cliente_1: str
    cpf_cliente_2: str

class CompraCreateModel(BaseModel):
    cpf_cliente: str
    idprod: int
    quantidade: int

postgres_pool = pool.SimpleConnectionPool(1, 10, POSTGRES_CONN_STRING)
mongo_client = MongoClient(MONGO_CONN_STRING)
mongo_db = mongo_client["minhaLojaDB"]
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


@app.get("/recomendacoes/{cpf}", summary="Obter Recomendações para um Cliente")
async def get_recomendacoes_amigos(cpf: str):
    cache_key = f"recomendacoes:{cpf}"
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            print(f"Cache HIT para recomendações do CPF: {cpf}")
            return json.loads(cached_data)

        print(f"Cache MISS para recomendações do CPF: {cpf}. Gerando recomendações...")

        cpfs_amigos = []
        with neo4j_driver.session() as session:
            result = session.run("MATCH (:Cliente {cpf: $cpf})-[:AMIGO_DE]->(amigo:Cliente) RETURN amigo.cpf AS cpf_amigo", cpf=cpf)
            cpfs_amigos = [record["cpf_amigo"] for record in result]

        if not cpfs_amigos: return []

        compras_collection = mongo_db["compras"]
        produtos_collection = mongo_db["produtos"]
        
        produtos_comprados_ids = []
        compras_amigos = compras_collection.find({"cpf_cliente": {"$in": cpfs_amigos}})
        for compra in compras_amigos:
            produtos_comprados_ids.append(compra["idprod"])

        ids_unicos = list(set(produtos_comprados_ids))
        if not ids_unicos: return []

        recomendacoes = list(produtos_collection.find({"idprod": {"$in": ids_unicos}}, {'_id': 0}))

        await redis_client.set(cache_key, json.dumps(recomendacoes), ex=3600)
        return recomendacoes
    except Exception as e:
        print(f"Ocorreu um erro ao gerar recomendações: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

@app.post("/clientes", status_code=201, summary="Criar um Novo Cliente")
async def criar_novo_cliente(cliente: ClienteCreateModel):
    sql_insert_query = "INSERT INTO clientes (cpf, rg, nome, telefone, email, endereco, dt_nasc) VALUES (%s, %s, %s, %s, %s, %s, %s);"
    dados_para_inserir = (
        cliente.cpf, cliente.rg, cliente.nome, cliente.telefone,
        cliente.email, cliente.endereco, cliente.dt_nasc
    )
    pg_conn = None
    try:
        pg_conn = postgres_pool.getconn()
        with pg_conn.cursor() as cur:
            cur.execute(sql_insert_query, dados_para_inserir)
        pg_conn.commit()

        with neo4j_driver.session() as session:
            session.run("""
                MERGE (c:Cliente {cpf: $cpf})
                ON CREATE SET c.nome = $nome, c.telefone = $telefone, c.email = $email
            """, cpf=cliente.cpf, nome=cliente.nome, telefone=cliente.telefone, email=cliente.email)

        return {"mensagem": f"Cliente '{cliente.nome}' criado com sucesso!"}
    except Exception as e:
        if pg_conn: pg_conn.rollback()
        raise HTTPException(status_code=400, detail=f"Erro ao criar cliente: {e}")
    finally:
        if pg_conn: postgres_pool.putconn(pg_conn)

@app.post("/produtos", status_code=201, summary="Adicionar um Novo Produto ao Catálogo")
async def criar_novo_produto(produto: ProdutoCreateModel):
    try:
        if mongo_db["produtos"].find_one({"idprod": produto.idprod}):
            raise HTTPException(status_code=409, detail=f"Produto com idprod {produto.idprod} já existe.")
        
        mongo_db["produtos"].insert_one(produto.model_dump())
        return {"mensagem": f"Produto '{produto.produto}' adicionado com sucesso!"}
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao criar produto: {e}")

@app.post("/amizades", status_code=201, summary="Criar uma Relação de Amizade")
async def criar_nova_amizade(amizade: AmizadeCreateModel):
    cypher_query = "MATCH (a:Cliente {cpf: $cpf1}), (b:Cliente {cpf: $cpf2}) MERGE (a)-[:AMIGO_DE]->(b) MERGE (b)-[:AMIGO_DE]->(a) RETURN a.nome AS nome1, b.nome AS nome2"
    try:
        with neo4j_driver.session() as session:
            result = session.run(cypher_query, cpf1=amizade.cpf_cliente_1, cpf2=amizade.cpf_cliente_2)
            record = result.single()
            if not record:
                raise HTTPException(status_code=404, detail="Um ou ambos os CPFs não foram encontrados.")
        
        await redis_client.delete(f"recomendacoes:{amizade.cpf_cliente_1}", f"recomendacoes:{amizade.cpf_cliente_2}")
        
        return {"mensagem": f"Amizade criada com sucesso entre {record['nome1']} e {record['nome2']}!"}
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao criar amizade: {e}")

@app.post("/compras", status_code=201, summary="Registar uma Nova Compra")
async def registrar_compra(compra: CompraCreateModel):
    pg_conn = None
    try:
        pg_conn = postgres_pool.getconn()
        with pg_conn.cursor() as cur:
            cur.execute("SELECT cpf FROM clientes WHERE cpf = %s", (compra.cpf_cliente,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Cliente com CPF {compra.cpf_cliente} não encontrado.")
        postgres_pool.putconn(pg_conn)
        pg_conn = None

        produto_collection = mongo_db["produtos"]
        produto = produto_collection.find_one({"idprod": compra.idprod})

        if not produto: raise HTTPException(status_code=404, detail="Produto não encontrado.")
        if produto["quantidade"] < compra.quantidade: raise HTTPException(status_code=400, detail="Estoque insuficiente.") # Alterado de "Stock"

        novo_estoque = produto["quantidade"] - compra.quantidade # Alterado de "novo_stock"
        valor_total = produto["preco"] * compra.quantidade

        produto_collection.update_one({"idprod": compra.idprod}, {"$set": {"quantidade": novo_estoque}}) # Alterado de "novo_stock"

        compra_collection = mongo_db["compras"]
        id_da_compra = compra_collection.count_documents({}) + 2001
        
        nova_compra_doc = {
            "idcompra": id_da_compra, "cpf_cliente": compra.cpf_cliente, "idprod": compra.idprod,
            "data_compra": datetime.now(), "quantidade": compra.quantidade, "valorpago": valor_total
        }
        compra_collection.insert_one(nova_compra_doc)

        await redis_client.delete(f"recomendacoes:{compra.cpf_cliente}")

        nova_compra_doc.pop('_id', None)
        nova_compra_doc['data_compra'] = nova_compra_doc['data_compra'].isoformat()
        
        return {"mensagem": "Compra registada com sucesso!", "dados_compra": nova_compra_doc}

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Erro ao registar compra: {e}")
        raise HTTPException(status_code=500, detail=f"Não foi possível processar a compra: {e}")
    finally:
        if pg_conn: postgres_pool.putconn(pg_conn)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
