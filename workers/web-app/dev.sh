#!/bin/sh
# Dev launcher pinned to a modern Node (wrangler requires >= 22; login shells
# may default to an older nvm version).
NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/v2[2-9]*/bin 2>/dev/null | sort -V | tail -1)
if [ -n "$NODE_BIN" ]; then
  export PATH="$NODE_BIN:$PATH"
fi
exec npm run dev
