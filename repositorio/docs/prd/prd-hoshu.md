# PRD — Hoshu: System & ERP Operations Orchestrator

## 1. Objetivo do Produto
Centralizar a operação técnica do ERP em ambientes Windows, eliminando erros manuais em três pilares:
1. Controle de status e ciclo de vida de serviços Windows monitorados.
2. Aplicação de patches com ciclo fechado de parada, backup, injeção e reinício.
3. Esteira de build (DevOps) que baixa código via Git e compila artefatos.

## 2. Requisitos Funcionais

### RF01: Gerenciamento de Serviços Windows
- O sistema deve carregar os serviços declarados em `config/services.json`.
- Deve consultar o status atual de cada serviço (Running, Stopped, StartPending, StopPending).
- Deve permitir comandos: Iniciar, Parar, Reiniciar.
- A ordem de parada deve ser inversa à ordem de subida definida no campo `order`.

### RF02: Pipeline de Aplicação de Patches
- Aceitar arquivos de atualização válidos (`.ptm`, `.upd`).
- Antes da aplicação: parar todos os serviços ativos da lista.
- Antes da aplicação: criar snapshot/backup com carimbo de data/hora no diretório `backup_path`.
- Executar aplicação via CLI.
- Se o código de saída for 0 (sucesso): religar os serviços e notificar.
- Se o código de saída for diferente de 0 (erro): restaurar backup, religar serviços e alertar falha.

### RF03: DevOps e Compilação Git
- Efetuar checkout/pull da branch ou tag informada pelo operador.
- Validar se o repositório local está limpo (sem alterações pendentes) antes de compilar.
- Disparar o compilador por linha de comando em processo isolado.
- Transmitir a saída de log do compilador em tempo real para o operador.

## 3. Escopo Negativo (O que o Hoshu NÃO faz)
- Não gerencia serviços do Windows fora dos declarados no `services.json`.
- Não faz edição manual de código-fonte de programas compilados.
- Não substitui o versionamento do Git (apenas opera como cliente de automação).