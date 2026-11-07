#!/usr/bin/env bash
# Remove only unused, exclusively staging-tagged images. No prune, force or volume operations.
set -euo pipefail

apply=false
case "${1:---dry-run}" in
  --dry-run) ;;
  --apply) apply=true ;;
  *) echo "Uso: bash $0 [--dry-run|--apply]" >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then
  echo 'Passe somente --dry-run ou --apply.' >&2
  exit 2
fi
command -v docker >/dev/null || { echo 'Docker não encontrado.' >&2; exit 1; }
docker info --format '{{.ServerVersion}}' >/dev/null

# No glob supplied to Docker: select exact repository names from its inventory.
listing=$(docker image ls --format '{{.Repository}}:{{.Tag}}')
candidates=()
while IFS= read -r ref; do
  [[ "$ref" == rubrica-staging-*:* && "$ref" != *':<none>' ]] || continue
  candidates+=("$ref")
done <<< "$listing"

eligible() {
  local ref="$1" users tags tag
  # Include stopped containers. ancestor also protects descendants conservatively.
  users=$(docker container ls -aq --filter "ancestor=$ref") || return 2
  if [[ -n "$users" ]]; then
    echo "[preservar] $ref: referenciada por container existente."
    return 1
  fi
  tags=$(docker image inspect --format '{{range .RepoTags}}{{println .}}{{end}}' "$ref") || return 2
  [[ -n "$tags" ]] || return 2
  while IFS= read -r tag; do
    [[ -n "$tag" ]] || continue
    if [[ "$tag" != rubrica-staging-*:* ]]; then
      echo "[preservar] $ref: imagem também identificada por $tag."
      return 1
    fi
  done <<< "$tags"
  return 0
}

printf 'Limpeza exclusiva de imagens Rúbrica staging | modo=%s\n' "$([[ "$apply" == true ]] && echo aplicar || echo simular)"
echo 'Containers, volumes, redes, secrets, arquivos e caches de build ficam preservados.'
echo 'Imagens externas, produção, Nexo, Platform Infra e SIB ficam preservadas.'
processed=0
for ref in "${candidates[@]}"; do
  if eligible "$ref"; then
    if [[ "$apply" == true ]]; then
      # Recheck immediately before deletion; never bypass Docker's usage protection.
      if eligible "$ref"; then
        echo "[remover] $ref"
        docker image rm "$ref"
        processed=$((processed+1))
      else
        code=$?
        [[ "$code" == 1 ]] || exit "$code"
      fi
    else
      echo "[candidata] $ref"
      processed=$((processed+1))
    fi
  else
    code=$?
    [[ "$code" == 1 ]] || exit "$code"
  fi
done
printf '[ok] Imagens %s: %d\n' "$([[ "$apply" == true ]] && echo removidas || echo candidatas)" "$processed"
echo 'O espaço efetivamente liberado pode ser menor que a soma das imagens: camadas e cache são compartilhados.'
docker system df
