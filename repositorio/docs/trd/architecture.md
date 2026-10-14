# TRD — Hoshu Technical Architecture

## 1. Stack e Restrições Técnicas
- **Ambiente Operacional:** Windows Server 2016 / 2019 / 2022 ou Windows 10/11 Pro (64-bit).
- **Privilégios:** O processo do Hoshu deve rodar com privilégios elevados de Administrador (para gerenciar o Service Control Manager do Windows).
- **Interação com Serviços Windows:**
  - Utilitário nativo `sc.exe` ou comandos PowerShell (`Get-Service`, `Start-Service`, `Stop-Service`).
  - Timeout padrão para parada de serviço: 60 segundos antes de escalonar para encerramento forçado.
- **Git Engine:** Executável `git` local via linha de comando com autenticação via SSH key configurada no host.

## 2. Padrões de Execução de Processos
- Toda chamada externa (Git, compilador, `sc.exe`) deve ser executada de forma assíncrona com captura de buffers separados para `stdout` e `stderr`.
- Tratamento estrito de códigos de saída (`exit code`). Códigos != 0 disparam exceções imediatas e interrompem a esteira.

## 3. Estrutura de Diretórios de Runtime
```text
C:\hoshu\
├── logs\            # Arquivos diários de auditoria (hoshu-YYYY-MM-DD.log)
├── workspace\       # Diretório temporário para pull do Git
└── backups\         # Snapshots de repositório antes de patches