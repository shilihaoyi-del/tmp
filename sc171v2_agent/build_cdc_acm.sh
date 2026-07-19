#!/usr/bin/env bash
set -euo pipefail
echo aidlux | sudo -S -p '' true

KVER=$(uname -r)
HDR=/usr/src/header
WORKDIR=/home/aidlux/cdc_acm_build
RAW_BASE="https://raw.githubusercontent.com/torvalds/linux/v5.4/drivers/usb/class"

echo "=== utsrelease ==="
cat "$HDR/include/generated/utsrelease.h" 2>/dev/null || echo "missing utsrelease"
uname -a

echo aidlux | sudo -S -p '' bash -c "mkdir -p /lib/modules/$KVER; ln -sfn $HDR /lib/modules/$KVER/build; ln -sfn $HDR /lib/modules/$KVER/source"

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

echo "=== download cdc-acm sources ==="
# try several mirrors
download() {
  local url="$1" out="$2"
  if command -v curl >/dev/null; then
    curl -fsSL --connect-timeout 20 -o "$out" "$url" && return 0
  fi
  if command -v wget >/dev/null; then
    wget -q -O "$out" "$url" && return 0
  fi
  return 1
}

OK=0
for base in \
  "https://raw.githubusercontent.com/torvalds/linux/v5.4/drivers/usb/class" \
  "https://cdn.jsdelivr.net/gh/torvalds/linux@v5.4/drivers/usb/class" \
  "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/usb/class?h=v5.4.197"
  do
  if download "$base/cdc-acm.c" cdc-acm.c && download "$base/cdc-acm.h" cdc-acm.h; then
    OK=1
    echo "downloaded from $base"
    break
  fi
  rm -f cdc-acm.c cdc-acm.h
done

if [ "$OK" != 1 ]; then
  echo "download failed, will embed minimal fallback later"
  exit 2
fi

ls -la cdc-acm.c cdc-acm.h
wc -l cdc-acm.c cdc-acm.h

cat > Makefile << 'EOF'
obj-m += cdc-acm.o
KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
EOF

echo "=== build ==="
make 2>&1
ls -la *.ko 2>&1
