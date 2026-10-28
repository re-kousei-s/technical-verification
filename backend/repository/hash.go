package repository

import "crypto/md5"

// md5Sum は、文字列の md5（16 バイト）。
func md5Sum(s string) [16]byte { return md5.Sum([]byte(s)) }
