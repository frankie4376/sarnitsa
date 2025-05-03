from flask import Flask, request
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import openai
import pymongo
import random
import threading
import time

from dotenv import load_dotenv
import os

load_dotenv()

VK_TOKEN = os.getenv("VK_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

print("VK_TOKEN:", VK_TOKEN)
print("OPENAI_API_KEY:", OPENAI_API_KEY)
print("MONGO_URI:", MONGO_URI)

# === ИНИЦИАЛИЗАЦИЯ ===
app = Flask(__name__)
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

openai.api_key = OPENAI_API_KEY
mongo_client = pymongo.MongoClient(MONGO_URI)

# Инициализация коллекций MongoDB
db = mongo_client.get_database()
players_collection = db['players']
log_collection = db['events_log']

# === ПОДСКАЗОЧНЫЕ ФУНКЦИИ ===

def send_vk(user_id, text):
    vk.messages.send(user_id=user_id, message=text, random_id=random.randint(1, 1_000_000))

def log_event(event_type, details):
    event = {"type": event_type, "details": details, "timestamp": time.time()}
    log_collection.insert_one(event)

def update_player(user_id, data):
    players_collection.update_one({"user_id": user_id}, {"$set": data}, upsert=True)

def get_player(user_id):
    player = players_collection.find_one({"user_id": user_id})
    if player:
        return player
    else:
        players_collection.insert_one({"user_id": user_id, "pogons": 2, "status": "active"})
        return {"user_id": user_id, "pogons": 2, "status": "active"}

# === ОБРАБОТКА КОМАНД ===

players = {}
group_status = {"разведка": False, "пехота": False}
events_log = []
game_state = {"day": 1, "phase": "morning"}

# Функции для работы с событиями
def random_event():
    events = [
        "Наткнулся на врага!",
        "Нашел аптечку!",
        "Погиб в засаде!",
        "Нашел скрытый путь!",
        "Попал в ловушку!"
    ]
    return random.choice(events)

def move_player(user_id, position):
    players[user_id] = {"position": position}

def get_position(user_id):
    return players.get(user_id, {}).get("position", "Неизвестно")

def set_group_status(group, status):
    group_status[group] = status

def check_for_run_violation(user_id):
    user = players.get(user_id)
    if user and user["pogons"] == 1:
        send_vk(user_id, "⚠️ Наказание за нарушение: -10 баллов за бег с одним погоном.")
        add_points("Команда1", -10)

def add_points(team, points):
    global game_state
    if team == "Команда1":
        game_state["team1"] += points
    elif team == "Команда2":
        game_state["team2"] += points
    log_event("points_updated", {"team": team, "points": points})

def cut_pogons(user_id, amount):
    user = players.get(user_id)
    if user and user["pogons"] > 0:
        user["pogons"] -= amount
        if user["pogons"] <= 0:
            user["status"] = "убит"
        send_vk(user_id, f"Погонов осталось: {user['pogons']}")
        log_event("cut_pogons", {"user_id": user_id, "new_pogons": user["pogons"]})

def update_game_state(state):
    global game_state
    game_state = state

def get_game_state():
    return game_state

# === ОБРАБОТКА КОМАНД ===

def handle_command(event):
    user_id = event.user_id
    text = event.text.lower()
    user = get_player(user_id)

    if "/start" in text:
        update_player(user_id, {"pogons": 2, "status": "active"})
        send_vk(user_id, "Добро пожаловать в Зарницу! Ты получаешь 2 погона.")
        return

    elif "/срезать погоны" in text:
        target_user_id = int(text.split()[1].replace("@", ""))  # Предполагаем, что @Игрок1
        cut_pogons(target_user_id, 1)

    elif "/баллы" in text:
        s = game_state
        send_vk(user_id, f"Очки:\nКоманда 1: {s.get('team1', 0)}\nКоманда 2: {s.get('team2', 0)}")

    # Другие команды аналогично

# === СЛУШАЕМ СОБЫТИЯ ОТ VK ===

def vk_polling():
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            handle_command(event)

# === Flask для проверки состояния сервера ===

@app.route('/')
def index():
    return "Бот запущен!"

# === ЗАПУСК ===
if __name__ == '__main__':
    threading.Thread(target=vk_polling).start()
    app.run(port=8000)
