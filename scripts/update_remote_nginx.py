import subprocess

conf = """# ComputeMesh High-Security & Anti-Eavesdropping Configuration (TLS 1.3 / GDPR Hardened)
proxy_hide_header X-Powered-By;
proxy_hide_header Server;

add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(self), interest-cohort=()" always;

location /v1/ {
    proxy_pass http://127.0.0.1:8000/v1/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_max_temp_file_size 0;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_max_temp_file_size 0;
}

location /node/ {
    proxy_pass http://127.0.0.1:8000/node/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_max_temp_file_size 0;
}

# llama.cpp WebUI & OpenAI API routes
location ~ ^/(props|slots|models|health|completion|completions|chat/completions|tokenize|detokenize|infill|metrics)(/.*)?$ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_max_temp_file_size 0;
}

location ~ ^/webui/(props|slots|models|health|completion|completions|chat/completions|v1/models|v1/chat/completions|tokenize|detokenize|infill)(/.*)?$ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_max_temp_file_size 0;
}
"""

p = subprocess.Popen(['ssh', 'root@mesh.inetconnector.com', 'cat > /var/www/vhosts/system/mesh.inetconnector.com/conf/vhost_nginx.conf && nginx -t && systemctl reload nginx'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
stdout, stderr = p.communicate(input=conf)
print('STDOUT:', stdout)
print('STDERR:', stderr)
print('RC:', p.returncode)
