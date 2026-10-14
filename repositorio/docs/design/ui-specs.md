

# UI Specifications — Painel Hoshu

## 1. framework
- Tabler.io
- tema dark ou white
- menu vertical com colapse

 
## 2. Visão Geral da Interface
Painel com layout focado em cockpit operacional, com feedback de status por cor:
- **Verde:** Serviço rodando (`Running`) / Build sucesso.
- **Cinza/Laranja:** Serviço parado (`Stopped`) / Operação em andamento.
- **Vermelho:** Erro / Serviço com falha (`Failed`).

## 3. Blocos Principais
1. **Configuração:** Crud de usuarios 
2. **Header:** Nome da máquina, status de privilégio (Admin: Sim/Não), hora do servidor.
3. **Painel de Serviços:** Tabela com Nome do Serviço, Porta, Status, Consumo de Memória e Botões de Ação (`Start`, `Stop`, `Restart`).
4. **Módulo Patch ERP:** Seletor de arquivo de patch, botão "Executar Atualização Segura", barra de progresso com as etapas (Parando -> Backup -> Patch -> Iniciando).
5. **Módulo DevOps:** Seletor de branch, commit hash atual, botão "Build", terminal com streaming do log do compilador em fundo escuro.