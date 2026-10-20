#!/usr/bin/env sh
# README media from the media run (see e2e/media.e2e.ts): stills shrunk to 540 px wide and the
# walkthrough video as a GIF. Needs ffmpeg.
#   MEDIA=1 pnpm e2e media --project=setup --project=phone && sh scripts/readme-media.sh
set -eu
out=../../docs/images
for name in plan plan-dark recipe cook shopping pantry diary import; do
  [ -f "$out/$name.png" ] || continue
  ffmpeg -y -loglevel error -i "$out/$name.png" -vf "scale=540:-1:flags=lanczos" "$out/$name.tmp.png"
  mv "$out/$name.tmp.png" "$out/$name.png"
done
dir=$(dirname "$(find test-results -name walkthrough.txt | head -1)")
read -r start end < "$dir/walkthrough.txt"
ffmpeg -y -loglevel error -ss "$start" -to "$end" -i "$dir/video.webm" \
  -vf "fps=10,scale=300:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" \
  -loop 0 "$out/walkthrough.gif"
ls -l "$out"
