#!/bin/bash
for p in 5760 5761 5762 5763; do
  if nc -z -G 1 127.0.0.1 "$p" 2>/dev/null; then
    echo "$p open"
  else
    echo "$p closed"
  fi
done
