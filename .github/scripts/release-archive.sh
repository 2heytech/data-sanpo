#!/usr/bin/env bash
# GitHub Release の添付ファイルとしてフォルダを保存する・戻す（design-changes #63・#64）。
# Release の添付ファイルは private リポジトリでも Artifacts の容量（無料500MB）に数えず、Actions のキャッシュのように
# 7日で消えたり10GBの上限で追い出されたりしない。1つ2GiBまでなので 1.9GB ごとに分割して
# <名前>.tar.zst.part-NN として上げる。1つのタグには最新の1組だけを残す。
#
#   release-archive.sh save <タグ> <名前> <基準フォルダ> <パス...>   基準フォルダからのパスを保存する
#   release-archive.sh latest <タグ> <名前の先頭>                    保存されている名前（並べて最後）を出す。なければ空
#   release-archive.sh restore <タグ> <名前> <展開先>                 保存したものを展開先に戻す
# 環境変数: GH_TOKEN、RUNNER_TEMP（作業場所）、GITHUB_SHA（Release を作るときのコミット）
set -euo pipefail
work="${RUNNER_TEMP:-/tmp}/release-archive"

assets() { gh release view "$1" --json assets --jq '.assets[].name' 2>/dev/null || true; }

case "${1:-}" in
  save)
    tag="${2:?}" name="${3:?}" base="${4:?}"; shift 4
    [ "$#" -gt 0 ] || { echo "保存するパスを指定してください" >&2; exit 2; }
    out="$work/save-$name"
    mkdir -p "$out"
    tar --zstd -c -C "$base" "$@" | split -b 1900m -d -a 2 - "$out/$name.tar.zst.part-"
    ls -l "$out" >&2
    notes="$name（コミット ${GITHUB_SHA:-不明}）。Data release が使う。手で消さないこと。"
    if gh release view "$tag" >/dev/null 2>&1; then
      gh release edit "$tag" --notes "$notes" >/dev/null
    else
      gh release create "$tag" --target "${GITHUB_SHA:-HEAD}" --title "$tag" --notes "$notes" --latest=false >/dev/null
    fi
    # 新しい分を上げ終えてから古い分を消す（途中で失敗しても前回分が残る）
    gh release upload "$tag" "$out/$name.tar.zst.part-"* --clobber
    for a in $(assets "$tag"); do
      case "$a" in "$name.tar.zst.part-"*) ;; *) gh release delete-asset "$tag" "$a" --yes ;; esac
    done
    echo "保存しました: Release $tag の $name" >&2
    ;;
  latest)
    tag="${2:?}" prefix="${3:?}"
    assets "$tag" | sed -n "s/^\\($prefix.*\\)\\.tar\\.zst\\.part-[0-9]*\$/\\1/p" | sort -u | tail -n 1
    ;;
  restore)
    tag="${2:?}" name="${3:?}" dest="${4:?}"
    mkdir -p "$work/restore-$name" "$dest"
    gh release download "$tag" --pattern "$name.tar.zst.part-*" --dir "$work/restore-$name" --clobber
    cat "$work/restore-$name/$name.tar.zst.part-"* | tar --zstd -x -C "$dest"
    rm -rf "${work:?}/restore-$name"
    ;;
  *)
    echo "使い方: $0 save <タグ> <名前> <基準フォルダ> <パス...> | latest <タグ> <名前の先頭> | restore <タグ> <名前> <展開先>" >&2
    exit 2
    ;;
esac
