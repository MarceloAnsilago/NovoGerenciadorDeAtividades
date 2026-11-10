# Horarios no Fly.io

Segunda a sexta, 07:30 ate 13:45, horario de Rondonia (UTC-4): manter as
Machines web ligadas. As 13:45, parar. Fora dessa janela, iniciar com acesso
e parar automaticamente por ociosidade. Sabados e domingos sao sob demanda.
O primeiro acesso a uma Machine parada aguarda a inicializacao do Django.

## Ativacao

1. Publicar estes arquivos na branch padrao `main` do repositorio.
2. Gerar um token restrito ao app, em um terminal autenticado no Fly:
   `flyctl tokens create deploy -a novogerenciadordeatividades --expiry 8760h`
3. No GitHub, em Settings > Secrets and variables > Actions, cadastrar
   `FLY_API_TOKEN` com o token gerado. Nao salvar o token em arquivos ou commits.
   Renovar esse segredo antes de expirar em um ano.
4. Em Actions > Horarios do Fly.io, executar Run workflow e conferir o resultado.
   A execucao manual aplica a regra correspondente ao horario atual.
5. Em um proximo deploy, executar o workflow novamente para reaplicar o minimo
   correspondente ao horario: `fly.toml` usa minimo zero como padrao economico.

O agendador usa 11:30 e 17:45 UTC, de segunda a sexta. GitHub Actions pode
atrasar ou deixar de executar agendamentos em periodos de sobrecarga: os
horarios nao sao garantidos. O script sempre calcula o horario atual antes de
agir. Uma abertura atrasada para depois das 13:45 nao liga a aplicacao.

A atualizacao da configuracao da Machine pode reinicia-la brevemente. O
encerramento das 13:45 pode interromper requisicoes em andamento. Um novo
acesso pode voltar a inicia-la imediatamente, conforme solicitado.

O workflow encontra as Machines com servicos a cada execucao, sem fixar IDs.
Ele preserva imagem, volumes, variaveis, recursos e demais configuracoes.
Nao altera Machines sem servicos (por exemplo, workers).

Referencias:
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://fly.io/docs/launch/autostop-autostart/
- https://fly.io/docs/machines/api/machines-resource/
