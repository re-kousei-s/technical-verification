FROM nginx:alpine
# スマホのブラウザは、カメラを使うページに HTTPS を要求する。検証用なので、適当な自己署名の証明書を作る
# （スマホでは最初に警告が出る → 「詳細 → 進む」）
RUN apk add --no-cache openssl \
 && mkdir -p /etc/nginx/certs \
 && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=hdt-gateway" \
      -keyout /etc/nginx/certs/key.pem -out /etc/nginx/certs/cert.pem
COPY nginx.conf /etc/nginx/conf.d/default.conf
