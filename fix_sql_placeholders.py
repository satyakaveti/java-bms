import re

filepath = '/Users/satyakaveti/Code/Workspace/Own/java-bms/main.py'
with open(filepath, 'r') as f:
    content = f.read()

content = content.replace("WHERE s.movie_id = %s AND t.city_id = ?", "WHERE s.movie_id = %s AND t.city_id = %s")
content = content.replace("WHERE s.movie_id = %s AND s.theater_id = ?", "WHERE s.movie_id = %s AND s.theater_id = %s")
content = content.replace("WHERE s.theater_id = %s AND s.screen_name = ?", "WHERE s.theater_id = %s AND s.screen_name = %s")
content = content.replace("WHERE mov.tollybo_movie_id = %s AND s.show_date = ?", "WHERE mov.tollybo_movie_id = %s AND s.show_date = %s")
content = content.replace("WHERE t.theater_id = ?", "WHERE t.theater_id = %s")
content = content.replace("AND s.show_date = ?", "AND s.show_date = %s")

with open(filepath, 'w') as f:
    f.write(content)

print("Remaining placeholders replaced in main.py")
