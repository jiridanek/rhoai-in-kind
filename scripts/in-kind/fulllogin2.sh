BASE=https://oauth-server.127.0.0.1.sslip.io
CB=https://rhods-dashboard.127.0.0.1.sslip.io
rm -f /tmp/kf3x/cookies.txt
R1=$(curl -sk -c /tmp/kf3x/cookies.txt -o /dev/null -w "%{redirect_url}" "$CB/")
R2=$(curl -sk -b /tmp/kf3x/cookies.txt -c /tmp/kf3x/cookies.txt -d "username=admin&password=password" "$R1" -o /dev/null -w "%{redirect_url}")
curl -sk -b /tmp/kf3x/cookies.txt -c /tmp/kf3x/cookies.txt -o /tmp/kf3x/final2-body.txt -D /tmp/kf3x/final2-head.txt "$R2"
grep -E "^HTTP|^location|^set-cookie" /tmp/kf3x/final2-head.txt | cut -c1-150
