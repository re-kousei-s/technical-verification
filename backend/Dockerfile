# --- 管理画面（React + TypeScript + Tailwind）をビルドする ---
FROM node:22-alpine AS admin
WORKDIR /admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY admin/ ./
RUN npm run build

# --- ビルド用：Go のコードを 1 つの実行ファイルにする（管理画面の成果物を埋め込む） ---
FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
COPY --from=admin /admin/dist ./web/admin_dist
RUN CGO_ENABLED=0 go build -o /out/backend .

# --- 実行用：小さな Alpine に、実行ファイルと ffmpeg（H.264 のデコード用）だけを入れる ---
FROM alpine:3.23
RUN apk add --no-cache ffmpeg ca-certificates tzdata
COPY --from=build /out/backend /usr/local/bin/backend
# ポートは、EXPOSE しない（外へ出すのは、gateway の ports だけ。コンテナ同士は、ネットワーク hdt-net の中で、backend:8000 などの名前で通信する）
CMD ["backend"]
