document.addEventListener('DOMContentLoaded', () => {
    const API_BASE_URL = 'http://localhost:8000';
    const loader = document.getElementById('loader');
    const notification = document.getElementById('notification');

    function showNotification(message, isError = false) {
        notification.textContent = message;
        notification.className = `p-4 mb-6 rounded-lg text-white ${isError ? 'bg-red-500' : 'bg-green-500'}`;
        notification.classList.remove('hidden');
        setTimeout(() => {
            notification.classList.add('hidden');
        }, 5000);
    }

    function toggleLoader(show) {
        loader.style.display = show ? 'flex' : 'none';
    }

    const btnGetRecomendacoes = document.getElementById('btn-get-recomendacoes');
    const recomendacoesResults = document.getElementById('recomendacoes-results');
    
    btnGetRecomendacoes.addEventListener('click', async () => {
        const cpf = document.getElementById('cpf-recomendacao-input').value;
        if (!cpf) {
            showNotification('Por favor, digite um CPF.', true);
            return;
        }

        toggleLoader(true);
        recomendacoesResults.innerHTML = '';
        
        try {
            const response = await fetch(`${API_BASE_URL}/recomendacoes/${cpf}`);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Erro ao buscar recomendações.');
            }
            
            if (data.length === 0) {
                recomendacoesResults.innerHTML = '<p class="text-gray-500 col-span-full text-center">Nenhuma recomendação encontrada para os amigos deste cliente.</p>';
            } else {
                data.forEach(produto => {
                    const card = `
                        <div class="bg-gray-700 border border-gray-600 p-4 rounded-lg shadow-sm">
                            <h4 class="font-bold text-lg text-white">${produto.produto}</h4>
                            <p class="text-gray-300">Preço: R$ ${produto.preco.toFixed(2)}</p>
                            <p class="text-gray-300">Em Estoque: ${produto.quantidade}</p>
                        </div>
                    `;
                    recomendacoesResults.innerHTML += card;
                });
            }

        } catch (error) {
            showNotification(error.message, true);
        } finally {
            toggleLoader(false);
        }
    });

    async function handleFormSubmit(formId, endpoint, successMessage) {
        const form = document.getElementById(formId);
        if (!form) return;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            toggleLoader(true);

            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());

            for(const key in data) {
                const input = form.querySelector(`[name="${key}"]`);
                if(input && input.type === 'number') {
                    if (data[key] !== '') {
                       data[key] = parseFloat(data[key]);
                    } else {
                       delete data[key]; 
                    }
                }
            }

            try {
                const response = await fetch(`${API_BASE_URL}${endpoint}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(data)
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.detail || 'Ocorreu um erro.');
                }
                
                showNotification(result.mensagem || successMessage);
                form.reset();

            } catch (error) {
                showNotification(error.message, true);
            } finally {
                toggleLoader(false);
            }
        });
    }

    // 2. Registrar os handlers para cada formulário
    handleFormSubmit('form-criar-cliente', '/clientes', 'Cliente criado com sucesso!');
    handleFormSubmit('form-criar-amizade', '/amizades', 'Amizade criada com sucesso!');
    handleFormSubmit('form-criar-produto', '/produtos', 'Produto adicionado com sucesso!');
    handleFormSubmit('form-registar-compra', '/compras', 'Compra registada com sucesso!');
});
