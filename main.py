import os
import asyncio
import requests
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask
from threading import Thread

# Настройка Flask для поддержания бота в активном режиме 24/7
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

USER_CHAT_ID = None

# Полный список ID отслеживаемых лиг
TOP_LEAGUES = [39, 140, 78, 135, 61, 2, 3, 848, 40, 88, 94, 203, 307, 253, 235]

def get_todays_fixtures():
    """Запрос матчей по всем отслеживаемым лигам на сегодня"""
    if not FOOTBALL_API_KEY:
        return []
    
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_fixtures = []
    headers = {"x-apisports-key": FOOTBALL_API_KEY}
    
    for league_id in TOP_LEAGUES:
        url = f"https://v3.football.api-sports.io/fixtures?date={today_date}&league={league_id}"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            data = response.json().get("response", [])
            all_fixtures.extend(data)
        except Exception as e:
            print(f"Ошибка запроса лиги {league_id}: {e}")
            
    return all_fixtures

def get_match_lineups(fixture_id):
    """Запрос составов текущего матча"""
    if not FOOTBALL_API_KEY:
        return []
        
    headers = {"x-apisports-key": FOOTBALL_API_KEY}
    lineups_url = f"https://v3.football.api-sports.io/fixtures/lineups?fixture={fixture_id}"
    
    try:
        response = requests.get(lineups_url, headers=headers, timeout=10)
        return response.json().get("response", [])
    except Exception as e:
        print(f"Ошибка получения составов: {e}")
        return []

def get_previous_match_starters(team_id):
    """Автоматическое получение стартового состава команды из её прошлого матча"""
    if not FOOTBALL_API_KEY:
        return []
        
    headers = {"x-apisports-key": FOOTBALL_API_KEY}
    url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=1"
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        fixtures = response.json().get("response", [])
        if not fixtures:
            return []
            
        last_fixture_id = fixtures[0].get("fixture", {}).get("id")
        lineups = get_match_lineups(last_fixture_id)
        
        for team_lineup in lineups:
            if team_lineup.get("team", {}).get("id") == team_id:
                return [p.get("player", {}).get("name") for p in team_lineup.get("startXI", [])]
    except Exception as e:
        print(f"Ошибка получения прошлого состава команды {team_id}: {e}")
        
    return []

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    global USER_CHAT_ID
    USER_CHAT_ID = message.chat.id
    await message.answer(
        "🛡 **Автоматический сканер ротации активирован!**\n\n"
        "• Бот отслеживает 15 лиг и автоматически сравнивает текущие составы с прошлыми матчами.\n"
        "• Сигнал приходит при ротации 3+ игроков старта."
    )

@dp.message(Command("testapi"))
async def test_api_cmd(message: types.Message):
    if not FOOTBALL_API_KEY:
        await message.answer("❌ Ошибка: Ключ не найден!")
        return
        
    fixtures = get_todays_fixtures()
    if fixtures:
        await message.answer(f"✅ Связь с API работает!\n🏆 Матчей в отслеживаемых лигах на сегодня: {len(fixtures)}")
    else:
        await message.answer("⚠️ В отслеживаемых лигах сегодня матчей не найдено.")

async def live_match_monitor():
    while USER_CHAT_ID is None:
        await asyncio.sleep(3)

    while True:
        try:
            fixtures = get_todays_fixtures()
            now = datetime.now(timezone.utc)
            
            for fixture in fixtures:
                fixture_id = fixture.get("fixture", {}).get("id")
                timestamp = fixture.get("fixture", {}).get("timestamp")
                match_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                league_name = fixture.get("league", {}).get("name", "Турнир")
                
                time_diff = (match_time - now).total_seconds() / 60
                
                # Проверка за 25-35 минут до матча
                if 25 <= time_diff <= 35:
                    teams_lineups = get_match_lineups(fixture_id)
                    
                    for team_data in teams_lineups:
                        team_id = team_data.get("team", {}).get("id")
                        team_name = team_data.get("team", {}).get("name")
                        current_start_xi = [p.get("player", {}).get("name") for p in team_data.get("startXI", [])]
                        coach = team_data.get("coach", {}).get("name")
                        
                        if current_start_xi:
                            prev_start_xi = get_previous_match_starters(team_id)
                            
                            if prev_start_xi:
                                # Находим игроков из прошлого старта, которых НЕТ в текущем старте
                                benched_or_missing = [p for p in prev_start_xi if p not in current_start_xi]
                                
                                # Если ротация затронула 3 и более игроков старта — отправляем сигнал
                                if len(benched_or_missing) >= 3:
                                    report = f"🚨 **ВНИМАНИЕ: СИЛЬНАЯ РОТАЦИЯ / ОСЛАБЛЕНИЕ!**\n"
                                    report += f"🏆 {league_name}\n"
                                    report += f"⚔️ Команда: **{team_name}**\n"
                                    report += f"-----------------------------------\n"
                                    report += f"🔄 **Заменено игроков старта:** {len(benched_or_missing)} из 11\n\n"
                                    report += f"❌ **Не вышли в старте (по сравнению с прошлым матчем):**\n"
                                    for p in benched_or_missing:
                                        report += f"• {p}\n"
                                    if coach:
                                        report += f"\n👔 Главный тренер: {coach}\n"
                                    
                                    await bot.send_message(USER_CHAT_ID, report, parse_mode="Markdown")
                                
        except Exception as e:
            print(f"Ошибка в фоновом цикле: {e}")
            
        await asyncio.sleep(1800) # Проверка каждые 30 минут

async def main():
    asyncio.create_task(live_match_monitor())
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())
