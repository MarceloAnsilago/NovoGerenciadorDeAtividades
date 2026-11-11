# Deploy Oracle por consulta ao GitHub

Implementação preparada, **não instalada nem ativada**. Nenhum push faz parte da
instalação. As referências locais analisadas mostram `oracle-production` em
`e99786ba` e `main` em `91a96755`, oito commits à frente. Não promova esses commits
para instalar o mecanismo. Fly.io, seus workflows e GFilas não são alterados.

## Modelo e aprovação

A Oracle consulta exclusivamente `refs/heads/oracle-production`. `main` não é
fonte de deploy Oracle. O workflow existente de `main` continua publicando no
Fly; portanto até um push de documentação em main mantém esse efeito existente.
Não há workflow novo, chave Oracle no GitHub, webhook nem SSH saindo do Windows.
`deploy.ps1 -Target Oracle` e `Ambos` foram bloqueados para impedir o caminho
antigo. O modo Fly permanece como estava.

**Antes de permitir deploy real, configure e confira a proteção no GitHub:**
Settings > Rules > Rulesets (ou Branches), regra ativa para `oracle-production`:

- Exigir pull request e pelo menos uma aprovação de outra pessoa autorizada.
- Invalidar aprovações após novos commits e exigir aprovação do último push.
- Bloquear force push e exclusão; aplicar também a administradores, sem bypass
  para bots, Actions ou a credencial usada pelo Codex.
- Limitar quem pode aprovar/mesclar à pessoa responsável por produção. Em conta
  pessoal, confira as opções disponíveis: restrição de atores depende do plano
  e do tipo de proprietário. Se necessário, use organização/equipe dedicada.
- A credencial do Codex não deve poder administrar regras, ignorá-las ou aprovar
  sua própria publicação. A Oracle precisa apenas de leitura do repositório.

A regra deve ser verificada com tentativa de push não autorizado **em ambiente
controlado**, sem alterar produção. Repositório privado pode exigir plano pago
para proteção. Se a conta não puder impor esses controles, mantenha o timer
inativo: esta implementação não substitui a autorização do GitHub. Nenhuma
proteção remota foi configurada ou verificada nesta execução local.

Depois, a aprovação é uma ação humana explícita: revisar o SHA/diff de uma PR
com base `oracle-production` e só então aprovar/mesclar. Não crie automação de
promoção a partir de main. Uma PR de main inclui todos os commits ancestrais;
para aprovar só alterações específicas, prepare uma branch a partir de produção
com os commits selecionados. A mesclagem deve manter o HEAD instalado como
ancestral da nova versão. Aplique a proteção antes de qualquer promoção.

Documentação GitHub:
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches

## Instalação na Oracle, sem publicar versões

Use o console/sessão administrativa já disponível na Oracle. Não precisa abrir
SSH a partir do Windows. Transporte somente os três arquivos revisados abaixo
por upload no console ou por um checkout **separado** de uma branch de preparação
no GitHub. Não faça pull/checkout de main em `/srv/gerenciador/app` para instalá-los.
Publicar uma branch de preparação futuramente não deve atualizar produção.
Os comandos seguintes assumem os arquivos revisados em `/tmp/oracle-deploy/`:
`oracle.sh`, `gerenciador-deploy.service` e `gerenciador-deploy.timer`.
Não baixe nem execute arquivos de uma branch mutável sem conferir seu conteúdo.

1. Inspecione a instalação e a automação anterior:

   ```bash
   cd /srv/gerenciador/app
   git status --short
   git rev-parse HEAD
   git remote get-url origin
   git ls-files -- .env '.env.*' media staticfiles '*.sqlite3' '*.db'
   systemctl cat gerenciador.service
   systemctl list-timers --all
   crontab -l
   sudo crontab -l
   sed -n '1,240p' /home/ubuntu/deploy-gerenciador/verificar.sh
   df -h /srv/gerenciador
   du -sh /srv/gerenciador/venv /srv/gerenciador/app/staticfiles
   ```

   Preserve `verificar.sh`. Seu conteúdo não está neste repositório e não foi
   inspecionado. Não o execute como parte do deploy antes de confirmar que ele
   apenas verifica; remova conflitos de cron/timers que atualizem código ou
   reiniciem o aplicativo automaticamente. O lock deste mecanismo coordena suas
   próprias execuções; não coordena scripts antigos ou comandos Git manuais.
   O serviço deve usar o projeto e venv informados e escutar atrás do Nginx local.
   O checkout deve estar limpo, sem dados/configurações versionados e sem merge
   em andamento. Se o `.env` ainda estiver versionado, pare para uma manutenção
   específica que preserve seu conteúdo; o script recusa esse caso.

2. Confirme ferramentas e permissões (Ubuntu já tem Git/Python no ambiente):

   ```bash
   command -v git flock curl gzip systemctl
   test -x /srv/gerenciador/venv/bin/python
   test -f /srv/gerenciador/app/.env
   sudo install -d -o ubuntu -g ubuntu -m 700 /srv/gerenciador/deploy-state
   sudo install -d -o ubuntu -g ubuntu -m 700 /srv/gerenciador/deploy-backups
   sudo install -d -o root -g root -m 755 /home/ubuntu/deploy-gerenciador
   ```

   `ubuntu` precisa poder escrever no checkout, venv, estáticos e diretórios de
   estado/backup. Não rode deploy como root. Não faça chown recursivo indiscriminado
   em mídia/configurações. Guarde espaço para cópia do venv quando requirements
   mudar, código e estáticos; falha de backup impede alteração da instalação.
   Backups não são apagados automaticamente: monitore disco e retenha ao menos o
   último backup válido antes de arquivar backups antigos manualmente.

3. Com `sudo visudo -f /etc/sudoers.d/gerenciador-deploy`, autorize somente:

   ```text
   ubuntu ALL=(root) NOPASSWD: /usr/bin/systemctl restart gerenciador.service
   ```

   Confira com `sudo visudo -cf /etc/sudoers.d/gerenciador-deploy` e
   `sudo -n -l /usr/bin/systemctl restart gerenciador.service`.
   Não dê sudo genérico, nem permissão de reiniciar Nginx/outros serviços.
   A unidade não usa NoNewPrivileges porque precisa desse sudo limitado.

4. O origin esperado é exatamente
   `https://github.com/MarceloAnsilago/NovoGerenciadorDeAtividades.git`.
   Para repo privado, configure credencial HTTPS somente leitura para `ubuntu`
   (Contents: read, restrita a esse repo), em armazenamento privado na Oracle,
   fora do checkout e nunca na URL, logs ou GitHub Secrets. Para repo público,
   leitura anônima basta. Teste sem imprimir credenciais:

   ```bash
   GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin refs/heads/oracle-production
   ```

5. Instale cópias revisadas, fora do checkout. Não sobrescreva `verificar.sh`:

   ```bash
   sudo install -o root -g root -m 755 /tmp/oracle-deploy/oracle.sh /home/ubuntu/deploy-gerenciador/oracle.sh
   sudo install -o root -g root -m 644 /tmp/oracle-deploy/gerenciador-deploy.service /etc/systemd/system/gerenciador-deploy.service
   sudo install -o root -g root -m 644 /tmp/oracle-deploy/gerenciador-deploy.timer /etc/systemd/system/gerenciador-deploy.timer
   bash -n /home/ubuntu/deploy-gerenciador/oracle.sh
   sudo systemd-analyze verify /etc/systemd/system/gerenciador-deploy.service /etc/systemd/system/gerenciador-deploy.timer
   sudo systemctl daemon-reload
   systemctl is-enabled gerenciador-deploy.timer
   systemctl is-active gerenciador-deploy.timer
   ```

   `disabled` e `inactive` são esperados (esses comandos retornam código não zero).
   **Não execute `enable`, `start` ou `--now` neste momento.** Se já existir um
   timer com esses nomes, inspecione e pare/desabilite o anterior antes da troca.
   Arquivos devem estar em LF e sem BOM; `.gitattributes` garante LF no Git.

## Teste sem alterações

Como `ubuntu`:

```bash
/home/ubuntu/deploy-gerenciador/oracle.sh --dry-run
```

Consulta o GitHub usando clone temporário, compara SHAs, verifica fast-forward,
proteção de caminhos e alteração de requirements. Não modifica checkout, refs,
venv, estado, estáticos, banco ou serviços; só cria e remove dados temporários.
Se HEAD já for produção, informa `Sem atualizacoes`. Se HEAD estiver à frente ou
divergente, recusa: revise a situação manualmente, sem reset forçado.
O dry-run não executa Django do candidato, não instala dependências nem garante
que ele iniciará; essas verificações pertencem ao deploy real. Confira também:

```bash
curl --fail --resolve gerenciador.celosmg.com.br:443:127.0.0.1 https://gerenciador.celosmg.com.br/login/ -o /dev/null
systemctl is-active gerenciador.service
```

O teste exige HTTPS válido no Nginx local e HTTP 200 no login. Se a instalação
usar outro domínio, altere **juntos** `health_url` e `--resolve` na cópia revisada.
Não use `-k` nem redirecionamentos que possam mascarar falhas.

## Operação futura, somente após aprovação

Deploy manual na Oracle (pode publicar a versão aprovada; não é teste):

```bash
/home/ubuntu/deploy-gerenciador/oracle.sh
```

Ou `sudo systemctl start gerenciador-deploy.service`, usando o mesmo script e lock.
Somente após autorizar a automação e concluir o teste manual:

```bash
sudo systemctl enable --now gerenciador-deploy.timer
```

Esse comando está documentado para uso futuro; **não foi executado**. O timer
consulta a cada cinco minutos, com pequeno atraso aleatório, sem polling contínuo.
Para suspendê-lo: `sudo systemctl disable --now gerenciador-deploy.timer`.
Consulte `journalctl -u gerenciador-deploy.service -n 100 --no-pager`,
`/srv/gerenciador/deploy-state/deployed` e os diretórios de backup.

## Validações, rollback e limites

Antes de modificar código: lock, árvore limpa, origem fixa, fast-forward, proteção
de `.env`, mídia, SQLite, estáticos gerados e links simbólicos; backup do código
instalado e dos estáticos. O venv inteiro é copiado apenas se requirements mudar.
Git não sobrescreve arquivos ignorados que colidam com o candidato.

Após atualizar: pip somente quando requirements mudar, `pip check`, Django
`check`, `makemigrations --check --dry-run`, `migrate --check --noinput`, depois
`collectstatic --noinput`. Nenhuma migração é aplicada. Só então reinicia
`gerenciador.service` e testa systemd + HTTP local. Registra SHA, horário UTC e
backup após sucesso. O endpoint de login verifica a resposta web, não uma prova
completa das funções da aplicação ou da conexão ao banco; `migrate --check`
verifica o acesso ao banco antes do reinício.

Uma falha restaura código/HEAD, venv (quando modificado) e estáticos. Se houve
tentativa de reinício, reinicia a versão anterior e testa sua resposta. Nenhum
comando de rollback altera Supabase, `.env`, mídia ou `/etc`. Sem `git clean`,
reset forçado, migração automática ou rollback de banco.

A versão que falhou recebe um marcador em `deploy-state/failed/SHA` e não é
repetida pelo timer. Após corrigir e revisar a causa, uma pessoa pode executar
`oracle.sh --retry-failed` (considere antes `--dry-run --retry-failed`). Um novo
SHA aprovado é avaliado normalmente. Falhas de rede/pré-validação não alteram a
instalação e podem ser verificadas novamente no próximo intervalo.

Interrupção abrupta ou rollback incompleto mantém `deploy-state/in-progress`
com SHA anterior, candidato e caminho do backup. Isso bloqueia novos deploys:
pare o timer, confira os três valores, inspecione checkout, venv, estáticos e
logs; restaure a versão anterior a partir do backup com manutenção assistida,
reinicie somente o serviço e valide HTTP. Preserve o backup e só remova o marcador
após confirmar a recuperação. Não tente resolver apagando o marcador às cegas.

A atualização acontece no checkout existente e não promete zero downtime:
processos podem ler arquivos durante a troca e o reinício tem uma janela de
indisponibilidade. Use horário de manutenção para mudanças de dependências.
A revisão humana de código aprovado continua necessária: Django e pip executam
código do candidato; não são uma sandbox contra commits maliciosos autorizados.
O script instalado e as unidades não se autoatualizam: novas versões exigem
revisão e instalação administrativa separada.

## Testes do repositório

```text
python -m unittest discover -s deploy/tests -v
bash -n deploy/oracle.sh
```

Os testes usam repositórios Git temporários reais, com Django, pip, HTTP e
systemd simulados. Cobrem ausência de atualização, dry-run, divergência, árvore
suja, caminhos protegidos, instalação condicional de dependências, migrações
pendentes, rollback de código/venv/estáticos, bloqueio de repetição e recuperação
incompleta. No Windows, o caso de flock real é pulado; rode a suíte também no
Ubuntu antes de ativar o timer. As unidades exigem `systemd-analyze verify` na
Oracle; o teste simulado não comprova a configuração do servidor.
