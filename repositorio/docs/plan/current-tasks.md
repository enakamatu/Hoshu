# Plano de Execução — Hoshu

## Sprint 1: Leitura de Configurações e Comandos de Serviços
- [x] Criar classe/módulo para carregar e validar `config/services.json`.
- [x] Criar adaptador do Windows Service Manager para consultar status de serviços (`sc query`).
- [x] Implementar métodos `start_service`, `stop_service` e `restart_service`.
- [x] Implementar verificação de privilégios de Administrador no processo.

## Sprint 2: DevOps & Automação Git
- [ ] Criar módulo gerenciador de Git com suporte a `clone`, `fetch`, `checkout` e `pull`.
- [ ] Criar runner assíncrono para execução do compilador CLI com captura de stdout/stderr.
- [ ] Implementar parser do log de compilação para capturar erros e avisos.

## Sprint 3: Engine de Aplicação de Patches
- [x] Implementar rotina de backup (cópia compactada ou snapshot dos arquivos do repositório/RPO).
- [ ] Construir orquestrador: Parada ordenada -> Backup -> Aplicação do Patch -> Start ordenado.
- [ ] Implementar mecanismo de Rollback automático se o patch tool retornar erro.

## Sprint 4: Painel / Endpoints de Controle
- [x] Expor endpoints ou interface para visualização dos serviços e disparo das rotinas.
- [x] Integrar streaming de logs em tempo real para a interface.