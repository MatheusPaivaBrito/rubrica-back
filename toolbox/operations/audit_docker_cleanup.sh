#!/usr/bin/env bash
# Read-only inventory. Never removes resources, reads env/secrets, or installs tools.
set -euo pipefail
umask 077

report_path="${1:-$PWD/rubrica-server-audit-$(date -u +%Y%m%dT%H%M%SZ).md}"
if [[ -e "$report_path" ]]; then
  echo "O arquivo já existe; escolha outro caminho: $report_path" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker não encontrado.' >&2
  exit 1
fi
if ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
  echo 'Sem acesso ao Docker. Execute com um usuário autorizado ao daemon.' >&2
  exit 1
fi

# Do not overwrite files or follow an existing symlink.
set -o noclobber
exec 3>"$report_path"
set +o noclobber
chmod 600 "$report_path"

section() {
  printf '\n## %s\n\n```text\n' "$1" >&3
  shift
  if ! "$@" >&3 2>&3; then
    printf '[informação indisponível; nenhuma correção foi tentada]\n' >&3
  fi
  printf '```\n' >&3
}

cat >&3 <<'INTRO'
# Inventário para planejar limpeza do servidor

Relatório somente de leitura. Nenhum container foi parado; nenhum recurso Docker,
arquivo de aplicação ou volume foi removido. O script cria somente este relatório.
Não coleta valores de secrets, variáveis de ambiente, logs, comandos dos containers
ou arquivos de configuração. Nomes, caminhos de montagem e topologia aparecem abaixo.

**Não interpretar “reclaimable”, “dangling” ou “sem container” como autorização de
exclusão.** Imagens antigas podem ser rollback; volumes sem vínculo podem conter dados.
O cache de build pode ser compartilhado entre staging e produção e fica preservado.
Containers parados também devem ser considerados ao proteger recursos de produção.
INTRO
section 'Data UTC' date -u '+%Y-%m-%dT%H:%M:%SZ'
section 'Host' hostname
section 'Arquitetura e kernel' uname -smr
section 'Uptime e carga' uptime
section 'Espaço em disco' df -hT
section 'Inodes' df -ih
section 'Memória' free -h
section 'Versões Docker' docker version --format 'Client={{.Client.Version}} Server={{.Server.Version}} OS={{.Server.Os}} Arch={{.Server.Arch}}'
section 'Resumo do daemon' docker info --format 'Root={{.DockerRootDir}} Driver={{.Driver}} CPUs={{.NCPU}} MemoryBytes={{.MemTotal}} Containers={{.Containers}} Running={{.ContainersRunning}} Stopped={{.ContainersStopped}} Images={{.Images}}'
section 'Uso agregado de imagens, containers, volumes e build cache' docker system df
section 'Todos os containers, inclusive parados' docker ps -a --no-trunc --format 'Name={{.Names}} ID={{.ID}} ImageRef={{.Image}} State={{.State}} Status={{.Status}} Created={{.CreatedAt}} Ports={{.Ports}}'
section 'Todas as imagens, inclusive sem tag' docker image ls -a --no-trunc --digests --format 'Repository={{.Repository}} Tag={{.Tag}} ID={{.ID}} Digest={{.Digest}} Created={{.CreatedAt}} Size={{.Size}}'
section 'Imagens sem tag (somente inventário, não são descartáveis automaticamente)' docker image ls --filter dangling=true --no-trunc --format 'ID={{.ID}} Repository={{.Repository}} Tag={{.Tag}} Size={{.Size}}'

printf '\n## Vínculos por container\n\n```text\n' >&3
while IFS= read -r container_id; do
  [[ -n "$container_id" ]] || continue
  # Inspect only allowlisted fields; never dump Config.Env, Args or full inspect.
  if ! docker container inspect --format 'Name={{.Name}} ID={{.Id}} ImageID={{.Image}} ImageRef={{.Config.Image}} State={{.State.Status}} Project={{index .Config.Labels "com.docker.compose.project"}} Service={{index .Config.Labels "com.docker.compose.service"}}
{{range .Mounts}}  Mount type={{.Type}} volume={{if eq .Type "volume"}}{{.Name}}{{else}}-{{end}} source={{.Source}} destination={{.Destination}} writable={{.RW}}
{{end}}{{range $network, $settings := .NetworkSettings.Networks}}  Network={{$network}}
{{end}}' "$container_id" >&3 2>&3; then
    printf '[container indisponível durante a coleta]\n' >&3
  fi
done < <(docker container ls -aq --no-trunc)
printf '```\n' >&3

printf '\n## Volumes e respectivos vínculos\n\n```text\n' >&3
while IFS= read -r volume_name; do
  [[ -n "$volume_name" ]] || continue
  if ! docker volume inspect --format 'Volume={{.Name}} Driver={{.Driver}} Created={{.CreatedAt}} Mountpoint={{.Mountpoint}} Project={{index .Labels "com.docker.compose.project"}} ComposeVolume={{index .Labels "com.docker.compose.volume"}}' "$volume_name" >&3 2>&3; then
    printf '[volume indisponível durante a coleta]\n' >&3
  fi
  docker container ls -a --filter "volume=$volume_name" --format '  UsedBy={{.Names}} State={{.State}} ImageRef={{.Image}}' >&3 2>&3 || true
done < <(docker volume ls -q)
printf '```\n' >&3

section 'Volumes sem vínculo atual (preservar até revisão)' docker volume ls --filter dangling=true --format 'Volume={{.Name}} Driver={{.Driver}}'
section 'Redes' docker network ls --no-trunc --format 'Name={{.Name}} ID={{.ID}} Driver={{.Driver}} Scope={{.Scope}}'
printf '\n## Identificação dos projetos nas redes\n\n```text\n' >&3
while IFS= read -r network_id; do
  [[ -n "$network_id" ]] || continue
  docker network inspect --format 'Name={{.Name}} Project={{index .Labels "com.docker.compose.project"}} Internal={{.Internal}}{{range .Containers}} Container={{.Name}}{{end}}' "$network_id" >&3 2>&3 || true
done < <(docker network ls -q)
printf '```\n' >&3

cat >&3 <<'END'

## Critérios para a revisão

- Preservar integralmente produção Rubrica, Nexo e Platform Infra: containers,
  imagens por ID (mesmo sem tag), volumes, bind mounts, redes e caches de build.
- O PostgreSQL `postgres:16-alpine` pode ser compartilhado por produção e staging:
  não remover uma imagem somente porque um container de staging a utiliza.
- Identificar staging pelo projeto Compose e conferir nomes e vínculos. Um nome
  de imagem, isoladamente, não prova que ela é exclusiva do staging.
- Não remover recursos desconhecidos, imagens de rollback nem volumes sem vínculo
  sem investigar sua origem e os backups.
- Este inventário não mede conteúdo de volumes nem percorre diretórios de dados.
  O resumo de build cache não permite provar exclusividade por ambiente.
- A coleta não é uma transação: recursos podem mudar enquanto ela é executada.
  Toda remoção futura exige reconferir os vínculos no momento da execução.
- A incompatibilidade ARM64 da imagem ClamAV é um problema separado; limpeza não
  corrige a ausência de manifest para essa arquitetura.
END
exec 3>&-
printf '[ok] Relatório criado: %s\n' "$report_path"
