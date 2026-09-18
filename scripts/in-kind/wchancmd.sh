P=$(pgrep -f ipykernel | head -1)
echo "pid=$P"
for t in /proc/$P/task/*; do
  w=$(cat $t/wchan 2>/dev/null)
  s=$(grep "^State:" $t/stat 2>/dev/null | awk "{print \$2}")
  echo "$w $s"
done | sort | uniq -c | sort -rn | head -8
