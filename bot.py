import os
import time
from datetime import datetime, timedelta

import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import threading
from dotenv import load_dotenv


load_dotenv()

# Замените 'YOUR_BOT_TOKEN' на токен вашего бота
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))


# Функция для создания соединения с базой данных
def create_connection():
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    return conn, cursor


# Создание таблиц, если они не существуют
def create_tables():
    conn, cursor = create_connection()
    cursor.execute('''CREATE TABLE IF NOT EXISTS accounts
                      (user_id INTEGER PRIMARY KEY,
                       balance REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS services
                      (service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       service_name TEXT,
                       price REAL,
                       type TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS completed_services
                      (service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       service_name TEXT,
                       price REAL,
                       photo_id TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS loans
                      (loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       amount REAL,
                       start_date TEXT,
                       end_date TEXT,
                       interest_rate REAL,
                       status TEXT)''')

    conn.commit()
    conn.close()


# Создание таблиц при запуске бота
create_tables()


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    conn, cursor = create_connection()
    user_id = message.from_user.id
    cursor.execute("INSERT OR IGNORE INTO accounts (user_id, balance) VALUES (?, 0)", (user_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, "Добро пожаловать в бот для покупки и оказания услуг!")


@bot.message_handler(commands=['loan'])
def show_loan_options(message):
    conn, cursor = create_connection()
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM loans WHERE user_id = ? AND status = 'active'", (user_id,))
    active_loan = cursor.fetchone()
    conn.close()

    markup = InlineKeyboardMarkup()
    if active_loan:
        loan_id, _, amount, _, end_date, interest_rate, _ = active_loan
        markup.add(InlineKeyboardButton(f"Погасить кредит ({amount} монет)", callback_data=f"repay_{loan_id}"))
    else:
        loan_amounts = [4, 8, 12, 16, 20]
        for amount in loan_amounts:
            markup.add(InlineKeyboardButton(f"{amount} монет", callback_data=f"loan_{amount}"))

    bot.reply_to(message, "Выберите действие:", reply_markup=markup)


@bot.message_handler(commands=['balance'])
def show_balance(message):
    conn, cursor = create_connection()
    cursor.execute("SELECT user_id, balance FROM accounts")
    accounts = cursor.fetchall()
    conn.close()

    balance_text = "Балансы счетов:\n"
    for account in accounts:
        user_id, balance = account
        if user_id == 0:
            balance_text += f"Банк: {balance}\n"
        else:
            try:
                user_info = bot.get_chat_member(chat_id=message.chat.id, user_id=user_id).user
                user_name = user_info.first_name
                balance_text += f"{user_name}: {balance}\n"
            except ApiTelegramException:
                balance_text += f"Пользователь {user_id}: {balance}\n"

    bot.reply_to(message, balance_text)


# Обработчик команды /buy
@bot.message_handler(commands=['buy'])
def show_buy_services(message):
    conn, cursor = create_connection()
    cursor.execute("SELECT service_id, service_name, price FROM services WHERE type = 'buy'")
    buy_services = cursor.fetchall()
    conn.close()
    markup = InlineKeyboardMarkup()
    for service in buy_services:
        service_id, service_name, price = service
        markup.add(InlineKeyboardButton(f"{service_name} - {price}", callback_data=f"buy_{service_id}"))
    bot.reply_to(message, "Выберите услугу для покупки:", reply_markup=markup)


# Обработчик команды /sell
@bot.message_handler(commands=['sell'])
def show_sell_services(message):
    conn, cursor = create_connection()
    cursor.execute("SELECT service_id, service_name, price FROM services WHERE type = 'sell'")
    sell_services = cursor.fetchall()
    conn.close()
    markup = InlineKeyboardMarkup()
    for service in sell_services:
        service_id, service_name, price = service
        markup.add(InlineKeyboardButton(f"{service_name} - {price}", callback_data=f"sell_{service_id}"))
    bot.reply_to(message, "Выберите услугу, которую можете оказать:", reply_markup=markup)


@bot.message_handler(commands=['debts'])
def show_debts(message):
    conn, cursor = create_connection()
    cursor.execute("SELECT user_id, amount, start_date, interest_rate FROM loans WHERE status = 'active'")
    loans = cursor.fetchall()
    conn.close()

    if loans:
        debts_text = "Состояние долгов пользователей:\n"
        for loan in loans:
            user_id, amount, start_date, interest_rate = loan
            start_date = datetime.strptime(start_date, "%Y-%m-%d")
            now = datetime.now()
            elapsed_time = now - start_date
            if amount <= 12:
                if elapsed_time <= timedelta(hours=24):
                    total_amount = amount
                    remaining_time = timedelta(hours=24) - elapsed_time
                else:
                    periods = (elapsed_time - timedelta(hours=24)) // timedelta(hours=24)
                    total_amount = amount * (1 + (periods + 1) * 0.25)
                    remaining_time = timedelta(hours=24) - ((elapsed_time - timedelta(hours=24)) % timedelta(hours=24))
            else:
                if elapsed_time <= timedelta(hours=48):
                    total_amount = amount
                    remaining_time = timedelta(hours=48) - elapsed_time
                else:
                    periods = (elapsed_time - timedelta(hours=48)) // timedelta(hours=72)
                    total_amount = amount * (1 + (periods + 1) * 0.25)
                    remaining_time = timedelta(hours=72) - ((elapsed_time - timedelta(hours=48)) % timedelta(hours=72))
            try:
                user_info = bot.get_chat_member(chat_id=message.chat.id, user_id=user_id).user
                user_name = user_info.first_name
                debts_text += f"{user_name}: {total_amount:.2f} монет, следующее увеличение через: {remaining_time}\n"
            except ApiTelegramException:
                debts_text += f"Пользователь {user_id}: {total_amount:.2f} монет, следующее увеличение через: {remaining_time}\n"
    else:
        debts_text = "Нет активных долгов"

    bot.reply_to(message, debts_text)


# Обработчик команды /send
@bot.message_handler(commands=['send'])
def send_money(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Банк", callback_data="send_bank"))
    conn, cursor = create_connection()
    cursor.execute("SELECT user_id FROM accounts WHERE user_id != 0")
    users = cursor.fetchall()
    conn.close()
    for user in users:
        user_id = user[0]
        try:
            user_info = bot.get_chat_member(chat_id=message.chat.id, user_id=user_id).user
            user_name = user_info.first_name
            markup.add(InlineKeyboardButton(user_name, callback_data=f"send_{user_id}"))
        except ApiTelegramException:
            markup.add(InlineKeyboardButton(f"Пользователь {user_id}", callback_data=f"send_{user_id}"))
    bot.reply_to(message, "Выберите получателя:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('send_'))
def select_recipient(call):
    recipient_id = call.data.split('_')[1]
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(chat_id=call.message.chat.id, text=f"Введите сумму для отправки {recipient_id}:")
    bot.register_next_step_handler(call.message, process_amount, recipient_id)


def process_amount(message, recipient_id):
    try:
        amount = float(message.text)
        user_id = message.from_user.id
        conn, cursor = create_connection()
        cursor.execute("SELECT balance FROM accounts WHERE user_id = ?", (user_id,))
        user_balance = cursor.fetchone()[0]
        if user_balance >= amount:
            cursor.execute("UPDATE accounts SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            if recipient_id == "bank":
                cursor.execute("UPDATE accounts SET balance = balance + ? WHERE user_id = 0", (amount,))
            else:
                cursor.execute("UPDATE accounts SET balance = balance + ? WHERE user_id = ?",
                               (amount, int(recipient_id)))
            conn.commit()
            recipient_name = "банк" if recipient_id == "bank" else recipient_id
            bot.send_message(chat_id=message.chat.id, text=f"Вы успешно отправили {amount} монет {recipient_name}.")
        else:
            bot.send_message(chat_id=message.chat.id, text="У вас недостаточно средств для отправки этой суммы.")
        conn.close()
    except ValueError:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, введите корректную сумму.")


# Обработчик команды /add_service
@bot.message_handler(commands=['add_service'])
def add_service(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Buy", callback_data="add_buy"))
    markup.add(InlineKeyboardButton("Sell", callback_data="add_sell"))
    bot.reply_to(message, "Выберите категорию для добавления услуги:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('add_'))
def select_category(call):
    category = call.data.split('_')[1]
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(chat_id=call.message.chat.id, text=f"Введите название услуги и ее стоимость для {category}:")
    bot.register_next_step_handler(call.message, process_service, category)


def process_service(message, category):
    try:
        text = message.text
        service_name, price = text.split(',')
        price = float(price.strip())
        conn, cursor = create_connection()
        cursor.execute("INSERT INTO services (service_name, price, type) VALUES (?, ?, ?)",
                       (service_name.strip(), price, category))
        conn.commit()
        conn.close()
        bot.send_message(chat_id=message.chat.id,
                         text=f"Услуга '{service_name.strip()}' стоимостью {price} монет успешно добавлена в категорию {category}.")
    except ValueError:
        bot.send_message(chat_id=message.chat.id,
                         text="Пожалуйста, введите корректное название и стоимость услуги в формате: название, стоимость.")


@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "Добро пожаловать! Вот список доступных команд и их описание:\n\n"
        "/start - Начало работы с ботом. Создает ваш аккаунт в системе, если его еще нет.\n\n"
        "/loan - Выберите сумму кредита, которую хотите взять, или погасите существующий кредит. Вы не можете взять новый кредит, пока не погасите текущий.\n\n"
        "/balance - Показывает баланс вашего счета и счета других пользователей.\n\n"
        "/buy - Показывает список доступных услуг для покупки.\n\n"
        "/sell - Показывает список услуг, которые вы можете оказать.\n\n"
        "/debts - Показывает текущие долги пользователей, включая накопленные проценты и время до следующего увеличения долга.\n\n"
        "/send - Отправить деньги другому пользователю или банку. Выберите получателя и введите сумму. Если у вас недостаточно средств, операция будет отменена.\n\n"
        "/add_service - Добавить новую услугу в категорию 'buy' или 'sell'. Сначала выберите категорию, затем введите название услуги и ее стоимость в формате: \"Имя услуги, стоимость\". Услуга будет добавлена в выбранную категорию.\n\n"
        "/waiting_list - Выберите пользователя и просмотрите его список дел. Для завершения задачи необходимо подтверждение от другого пользователя.\n\n"
        "Дополнительная информация:\n"
        "Экспресс услуги - Эти услуги обрабатываются быстрее и имеют разные правила обработки финансовых операций."
    )
    bot.reply_to(message, help_text)


@bot.message_handler(commands=['waiting_list'])
def show_waiting_list(message):
    markup = InlineKeyboardMarkup()
    conn, cursor = create_connection()
    cursor.execute("SELECT user_id FROM accounts WHERE user_id != 0")
    users = cursor.fetchall()
    conn.close()
    for user in users:
        user_id = user[0]
        if user_id != message.from_user.id:
            try:
                user_info = bot.get_chat_member(chat_id=message.chat.id, user_id=user_id).user
                user_name = user_info.first_name
                markup.add(InlineKeyboardButton(user_name, callback_data=f"waiting_{user_id}"))
            except ApiTelegramException:
                markup.add(InlineKeyboardButton(f"Пользователь {user_id}", callback_data=f"waiting_{user_id}"))
    bot.reply_to(message, "Выберите пользователя, чтобы увидеть его список дел:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('waiting_'))
def show_user_tasks(call):
    user_id = call.data.split('_')[1]
    conn, cursor = create_connection()
    cursor.execute("SELECT service_id, service_name FROM completed_services WHERE user_id = ?", (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    markup = InlineKeyboardMarkup()
    if tasks:
        for task in tasks:
            service_id, service_name = task
            markup.add(InlineKeyboardButton(service_name, callback_data=f"task_{service_id}_{user_id}"))
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text="Список дел пользователя:", reply_markup=markup)
    else:
        bot.send_message(chat_id=call.message.chat.id, text="У пользователя нет дел.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('task_'))
def confirm_task_completion(call):
    service_id, task_user_id = call.data.split('_')[1], call.data.split('_')[2]
    if call.from_user.id == int(task_user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Подтвердить выполнение", callback_data=f"confirm_{service_id}_{task_user_id}"))
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text="Подтвердите выполнение задачи:", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "Вы не можете подтвердить выполнение задачи другого пользователя.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_'))
def confirm_task(call):
    service_id, task_user_id = call.data.split('_')[1], call.data.split('_')[2]
    if call.from_user.id != int(task_user_id):
        conn, cursor = create_connection()
        cursor.execute("DELETE FROM completed_services WHERE service_id = ?", (service_id,))
        conn.commit()
        conn.close()
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text=f"Пользователь успешно закончил дело.")
    else:
        bot.answer_callback_query(call.id, "Вы не можете подтвердить выполнение своей задачи.")


def update_loans():
    while True:
        conn, cursor = create_connection()
        cursor.execute("SELECT loan_id, user_id, amount, start_date, interest_rate FROM loans WHERE status = 'active'")
        loans = cursor.fetchall()
        for loan in loans:
            loan_id, user_id, amount, start_date, interest_rate = loan
            start_date = datetime.strptime(start_date, "%Y-%m-%d")
            now = datetime.now()
            elapsed_time = now - start_date

            if amount <= 12:
                if elapsed_time > timedelta(hours=24):
                    new_interest_rate = interest_rate + 0.25 * (
                                (elapsed_time - timedelta(hours=24)) // timedelta(hours=24) + 1)
                    cursor.execute("UPDATE loans SET status = 'closed' WHERE loan_id = ?", (loan_id,))
                    cursor.execute(
                        "INSERT INTO loans (user_id, amount, start_date, interest_rate, status) VALUES (?, ?, ?, ?, 'active')",
                        (user_id, amount, now.strftime("%Y-%m-%d"), new_interest_rate))
            else:
                if elapsed_time > timedelta(hours=48):
                    new_interest_rate = interest_rate + 0.25 * (
                                (elapsed_time - timedelta(hours=48)) // timedelta(hours=72) + 1)
                    cursor.execute("UPDATE loans SET status = 'closed' WHERE loan_id = ?", (loan_id,))
                    cursor.execute(
                        "INSERT INTO loans (user_id, amount, start_date, interest_rate, status) VALUES (?, ?, ?, ?, 'active')",
                        (user_id, amount, now.strftime("%Y-%m-%d"), new_interest_rate))
        conn.commit()
        conn.close()
        time.sleep(60)  # Проверка каждую минуту


loan_thread = threading.Thread(target=update_loans)
loan_thread.start()
bot.polling()
