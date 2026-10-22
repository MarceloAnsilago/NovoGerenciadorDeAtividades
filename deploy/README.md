# Deploy pelo VS Code

O Fly continua configurado em `fly.toml`. A Oracle usa a instalacao existente em
`/srv/gerenciador/app`, ambiente `/srv/gerenciador/venv` e servico
`gerenciador.service`, com Nginx em frente ao Gunicorn.

## Configurar acesso a Oracle uma vez

1. Confirme o usuario com `whoami` na sessao SSH da Oracle e localize a chave
   privada usada para acessar a VPS. Nao coloque a chave no repositorio.
2. No PowerShell, na raiz do projeto:

   ```powershell
   Copy-Item deploy/oracle.example.json deploy/oracle.local.json
   ```

3. Preencha `User` e `IdentityFile` no arquivo local. Para caminhos Windows em
   JSON, use barras `/`, por exemplo `C:/Users/seu-usuario/.ssh/oracle.key`.
   `IdentityFile` pode ficar vazio se o OpenSSH ja usa ssh-agent/config.
   Esse arquivo local e ignorado pelo Git.
4. Conecte manualmente com `ssh -i CAMINHO_DA_CHAVE USUARIO@147.15.25.68`
   e confirme a identidade do host no primeiro acesso.
5. O usuario precisa escrever no projeto e no ambiente virtual, acessar o GitHub
   pelo Git da VPS e reiniciar o servico com `sudo -n`. Se faltar permissao,
   o administrador pode usar `visudo` para autorizar **somente**:

   ```text
   USUARIO ALL=(root) NOPASSWD: /usr/bin/systemctl restart gerenciador.service
   ```

   Confirme antes o caminho de `systemctl` com `command -v systemctl`.
6. Execute a tarefa `Deploy: verificar acesso Oracle` no VS Code. Essa tarefa
   verifica o SSH, os caminhos e a permissao de reinicio, sem atualizar o app.

## Publicar alteracoes

Salve os arquivos e faca commit de todas as alteracoes. No VS Code, abra
**Terminal > Executar Tarefa** e escolha:

- **Deploy: Oracle**: envia a branch atual ao GitHub; na VPS, busca a mesma
  revisao, atualiza por fast-forward, instala dependencias, verifica Django e
  migracoes pendentes, coleta estaticos e reinicia o servico.
- **Deploy: Fly**: executa o deploy existente com `flyctl`.
- **Deploy: Oracle e Fly**: publica primeiro na Oracle e depois no Fly. Se a
  Oracle falhar, interrompe antes de publicar no Fly.

Equivalentes pelo terminal:

```powershell
.\deploy.ps1 -Target Oracle -CheckOnly
.\deploy.ps1 -Target Oracle
.\deploy.ps1 -Target Fly
.\deploy.ps1 -Target Ambos
```

O repositorio da Oracle precisa ter o mesmo `origin` do projeto local, estar
limpo e ter historico compativel com a branch enviada. Nao ha reset forcado.
Os dois destinos recebem o commit selecionado; arquivos ignorados pelo Git nao
sao enviados a Oracle. Arquivos estaticos necessarios devem estar versionados
ou ja existir no servidor.

O deploy Oracle nao altera `.env`, Nginx nem executa migracoes no Supabase.
Se houver migracoes pendentes, ele para antes do reinicio. Combine a aplicacao
dessas migracoes separadamente, considerando que os dois ambientes podem usar
o mesmo banco.

Os deploys sao sequenciais, sem rollback automatico. Uma falha depois da
atualizacao do Git pode deixar codigo/dependencias atualizados no disco;
revise a saida antes de tentar novamente. O teste final verifica o systemd;
confirme tambem o acesso a https://gerenciador.celosmg.com.br e ao Fly.
