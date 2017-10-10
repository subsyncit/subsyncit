#!/bin/sh

dd if=/dev/zero bs=1000000 count=$2 2>/dev/null | openssl enc -rc4-40 -pass pass:weak  > "$1"