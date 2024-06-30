import time
from datetime import datetime, timedelta
from sqlalchemy import text
import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import logging
from config import *
from database import get_session, close_session

bot = telebot.TeleBot(BOT_TOKEN)

# Enable logging to help with debugging
logging.basicConfig(level=logging.DEBUG)


# Функция для создания соединения с базой данных
def create_connection():
    session = get_session()
    return session


# Создание таблиц, если они не существуют
def create_tables():
    logging.debug(f"create_connection data: {create_connection()}")

    session = create_connection()
    session.execute(text('''CREATE TABLE IF NOT EXISTS accounts
                      (user_id INTEGER PRIMARY KEY,
                       balance REAL)'''))

    session.execute(text('''CREATE TABLE IF NOT EXISTS services
                      (service_id SERIAL PRIMARY KEY,
                       service_name TEXT,
                       price REAL,
                       type TEXT)'''))

    session.execute(text('''CREATE TABLE IF NOT EXISTS completed_services
                      (service_id SERIAL PRIMARY KEY,
                       user_id INTEGER,
                       service_name TEXT,
                       price REAL,
                       type TEXT,
                       status TEXT,
                       end_date TEXT)'''))

    session.execute(text('''CREATE TABLE IF NOT EXISTS loans
                      (loan_id SERIAL PRIMARY KEY,
                       user_id INTEGER,
                       amount REAL,
                       start_date TEXT,
                       end_date TEXT,
                       interest_rate REAL,
                       status TEXT)'''))

    session.commit()
    session.close()


# Создание таблиц при запуске бота
create_tables()


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    session = create_connection()
    user_id = message.from_user.id
    session.execute(text("INSERT INTO accounts (user_id, balance) VALUES (0, 0) ON CONFLICT (user_id) DO NOTHING"))
    session.execute(text("INSERT INTO accounts (user_id, balance) VALUES (:user_id, 0)"
                         " ON CONFLICT (user_id) DO NOTHING"), {'user_id': user_id})
    session.commit()
    session.close()
    bot.reply_to(message, "Добро пожаловать в бот для покупки и оказания услуг!")


@bot.message_handler(commands=['change_balance'])
def change_balance(message):
    markup = InlineKeyboardMarkup()
    session = create_connection()
    users = session.execute(text("SELECT user_id FROM accounts")).fetchall()
    session.close()
    for user in users:
        user_id = user[0]
        try:
            user_info = bot.get_chat_member(chat_id=message.chat.id, user_id=user_id).user
            user_name = user_info.first_name
            if user_info.last_name:
                user_name += f" {user_info.last_name}"
            markup.add(InlineKeyboardButton(user_name, callback_data=f"select_{user_id}"))
        except ApiTelegramException:
            markup.add(InlineKeyboardButton(f"Пользователь {user_id}", callback_data=f"select_{user_id}"))
    bot.reply_to(message, "Выберите пользователя для изменения баланса:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def select_user(call):
    target_user_id = int(call.data.split('_')[1])
    clicking_user_id = call.from_user.id
    if target_user_id != 0:
        user_info = bot.get_chat_member(chat_id=call.message.chat.id, user_id=target_user_id).user
        user_name = user_info.first_name
        if user_info.last_name:
            user_name += f" {user_info.last_name}"
    else:
        user_name = 'Банк'
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(chat_id=call.message.chat.id, text=f"Введите сумму для изменения баланса пользователя {user_name}:")
    bot.register_next_step_handler(call.message, process_balance_change, target_user_id, user_name, clicking_user_id)


def process_balance_change(message, target_user_id, user_name, clicking_user_id):
    try:
        amount = float(message.text)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Подтвердить", callback_data=f"confirm_balance_{target_user_id}_{amount}_{clicking_user_id}"))
        markup.add(InlineKeyboardButton("Отменить", callback_data="cancel"))
        bot.send_message(chat_id=message.chat.id, text=f"Подтвердите изменение баланса на {amount} монет для пользователя {user_name}:", reply_markup=markup)
    except ValueError:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, введите корректную сумму.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_balance_'))
def handle_confirm_balance(call):
    data = call.data.split('_')
    target_user_id = int(data[2])
    amount = float(data[3])
    clicking_user_id = int(data[4])
    logging.debug(f"clicking_id: {clicking_user_id}, target_id: {target_user_id}, call_from: {call.from_user.id}")

    if call.from_user.id == clicking_user_id:

        bot.answer_callback_query(call.id, "Вы не можете подтвердить изменение собственного баланса.")
        return

    session = create_connection()
    session.execute(text("UPDATE accounts SET balance = :amount WHERE user_id = :user_id"),
                    {'amount': amount, 'user_id': target_user_id})
    session.commit()
    session.close()

    if target_user_id != 0:
        user_info = bot.get_chat_member(chat_id=call.message.chat.id, user_id=target_user_id).user
        user_name = user_info.first_name
        if user_info.last_name:
            user_name += f" {user_info.last_name}"
    else:
        user_name = 'Банк'

    bot.send_message(chat_id=call.message.chat.id, text=f"Баланс пользователя {user_name} успешно изменен на {amount} монет.")
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def handle_cancel(call):
    bot.send_message(chat_id=call.message.chat.id, text="Операция изменения баланса отменена.")
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)


@bot.message_handler(commands=['loan'])
def show_loan_options(message):
    session = create_connection()
    user_id = message.from_user.id
    active_loan = session.execute(text("SELECT * FROM loans "
                                       "WHERE user_id = :user_id AND status = 'active'"), {'user_id':user_id}).fetchone()
    session.close()

    markup = InlineKeyboardMarkup()
    if active_loan:
        loan_id, _, amount, _, end_date, interest_rate, _ = active_loan
        markup.add(InlineKeyboardButton(f"Погасить кредит ({amount} монет)", callback_data=f"repay_{loan_id}"))
    else:
        loan_amounts = [4, 8, 12, 16, 20]
        for amount in loan_amounts:
            markup.add(InlineKeyboardButton(f"{amount} монет", callback_data=f"loan_{amount}"))

    bot.reply_to(message, "Выберите действие:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('repay_'))
def handle_repay_loan(call):
    logging.debug(f"Received callback data: {call.data}")
    loan_id = int(call.data.split('_')[1])
    session = create_connection()
    loan = session.execute(text("SELECT user_id, amount, interest_rate FROM loans"
                                " WHERE loan_id = :loan_id AND status = 'active'"), {'loan_id': loan_id}).fetchone()

    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)

    if loan:
        user_id, amount, interest_rate = loan
        user_balance = session.execute(text("SELECT balance FROM accounts"
                                            " WHERE user_id = :user_id"), {'user_id': user_id}).fetchone()[0]
        total_amount = amount
        if user_balance >= total_amount:
            session.execute(text("UPDATE accounts SET balance = balance - :total_amount"
                                 " WHERE user_id = :user_id"), {'total_amount': total_amount, 'user_id': user_id})
            session.execute(text("UPDATE accounts SET balance = balance + :total_amount"
                                 " WHERE user_id = 0"), {'total_amount': total_amount})
            session.execute(text("UPDATE loans SET status = 'closed' WHERE loan_id = :loan_id"), {'loan_id': loan_id})
            session.commit()
            bot.send_message(chat_id=call.message.chat.id,
                             text=f"Кредит на сумму {total_amount:.2f} монет успешно погашен.")
        else:
            bot.send_message(chat_id=call.message.chat.id, text="У вас недостаточно средств для погашения кредита.")
    else:
        bot.send_message(chat_id=call.message.chat.id, text="Кредит не найден.")
    session.close()


@bot.callback_query_handler(func=lambda call: call.data.startswith('loan_'))
def handle_loan(call):
    logging.debug(f"Received callback data: {call.data}")
    amount = int(call.data.split('_')[1])
    user_id = call.from_user.id
    session = create_connection()

    bank_balance = session.execute(text("SELECT balance FROM accounts WHERE user_id = 0")).fetchone()[0]

    active_loan = session.execute(text("SELECT * FROM loans"
                                       " WHERE user_id = :user_id AND status = 'active'"),
                                  {'user_id', user_id}).fetchone()

    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)

    if active_loan:
        bot.send_message(chat_id=call.message.chat.id,
                         text="Вы не можете взять новый кредит, пока не погасите текущий.")
    elif bank_balance >= amount:
        session.execute(text("UPDATE accounts SET balance = balance - :amount WHERE user_id = 0"), {'amount': amount})
        session.execute(text("UPDATE accounts SET balance = balance + :amount"
                             " WHERE user_id = :user_id"), {'amount': amount, 'user_id': user_id})
        session.execute(text(
            "INSERT INTO loans (user_id, amount, start_date, end_date, interest_rate, status)"
            " VALUES (:user_id, :amount, :start_date, :end_date, :interest_rate, :status)"),
            {'user_id': user_id,
             'amount': amount,
             'start_date': datetime.now().strftime("%Y-%m-%d"),
             'end_date': '',
             'interest_rate': 0.25,
             'status': 'active'}
        )
        session.commit()
        bot.send_message(chat_id=call.message.chat.id, text=f"Кредит на сумму {amount} монет успешно выдан.")
    else:
        bot.send_message(chat_id=call.message.chat.id, text="В банке недостаточно средств для выдачи кредита.")
    session.close()


@bot.message_handler(commands=['balance'])
def show_balance(message):
    session = create_connection()
    accounts = session.execute(text("SELECT user_id, balance FROM accounts")).fetchall()
    session.close()

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
    session = create_connection()
    buy_services = session.execute(text("SELECT service_id, service_name, price FROM services "
                                        "WHERE type = 'buy'")).fetchall()
    session.close()
    markup = InlineKeyboardMarkup()
    for service in buy_services:
        service_id, service_name, price = service
        markup.add(InlineKeyboardButton(f"{service_name} - {price}", callback_data=f"buy_{service_id}"))
    bot.reply_to(message, "Выберите услугу для покупки:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy_service(call):
    logging.debug(f"Received callback data: {call.data}")
    service_id = int(call.data.split('_')[1])
    buyer_id = call.from_user.id

    session = create_connection()

    service = session.execute(text("SELECT service_name, price, type FROM services"
                                   " WHERE service_id = :service_id"), {'service_id': service_id}).fetchone()
    executor_id = session.execute(text("SELECT user_id FROM accounts"
                                       " WHERE user_id != 0 AND user_id != :buyer_id"),
                                  {'buyer_id': buyer_id}).fetchone()[0]
    buyer_balance = session.execute(text("SELECT balance FROM accounts "
                                         "WHERE user_id = :buyer_id"), {'buyer_id': buyer_id}).fetchone()[0]
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)

    if service:
        service_name, price, type = service
        if buyer_balance >= price:
            if service_name.startswith("Экспресс"):
                session.execute(text("UPDATE accounts SET balance = balance - :price WHERE user_id = :buyer_id"),
                                {'price': price, 'buyer_id': buyer_id}
                                )
                session.execute(text("UPDATE accounts SET balance = balance + :price WHERE user_id = 0"),
                                {'price': price}
                                )
                bot.send_message(chat_id=call.message.chat.id, text=f"Вы выбрали услугу '{service_name}'"
                                                                    f" стоимостью {price} монет. Все средства "
                                                                    f"переведены в банк.")
            else:
                logging.debug(f"Price: {price}")
                session.execute(text("UPDATE accounts SET balance = balance + :price WHERE user_id = 0"),
                                {'price': price * 0.25 - price * 0.75}
                                )
                session.execute(text("UPDATE accounts SET balance = balance - :price WHERE user_id = :buyer_id"),
                                {'price': price + price * 0.75, 'buyer_id': buyer_id}
                                )
                session.execute(text("UPDATE accounts SET balance = balance + :price "
                                     "WHERE user_id = (SELECT user_id FROM services WHERE service_id = :service_id)"),
                                {'price': price * 0.75, 'service_id': service_id}
                                )
                bot.send_message(chat_id=call.message.chat.id,
                                 text=f"Вы выбрали услугу '{service_name}' стоимостью {price} монет."
                                      f" 75% средств переведены исполнителю, 25% - в банк.")
            session.execute(text(
                "INSERT INTO completed_services (user_id, service_name, price, type, status)"
                " VALUES (:executor_id, :service_name, :price, :type, :status)"),
                {'executor_id': executor_id,
                 'service_name': service_name,
                 'price': price,
                 'type': type,
                 'status': 'active'}
            )
            session.commit()
        else:
            bot.send_message(chat_id=call.message.chat.id, text="У вас недостаточно средств для покупки этой услуги.")
    else:
        bot.send_message(chat_id=call.message.chat.id, text="Ошибка: услуга не найдена.")
    session.close()


# Обработчик команды /sell
@bot.message_handler(commands=['sell'])
def show_sell_services(message):
    session = create_connection()
    sell_services = session.execute(text("SELECT service_id, service_name, price FROM services "
                                         "WHERE type = 'sell'")).fetchall()
    session.close()
    markup = InlineKeyboardMarkup()
    for service in sell_services:
        service_id, service_name, price = service
        markup.add(InlineKeyboardButton(f"{service_name} - {price}", callback_data=f"sell_{service_id}"))
    bot.reply_to(message, "Выберите услугу, которую можете оказать:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('sell_'))
def handle_sell_service(call):
    logging.debug(f"Received callback data: {call.data}")
    service_id = int(call.data.split('_')[1])
    session = create_connection()
    service = session.execute(text("SELECT service_name, price, type FROM services"
                                   " WHERE service_id = :service_id"), {'service_id': service_id}).fetchone()
    session.close()
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    if service:
        service_name, price, type = service
        bot.send_message(chat_id=call.message.chat.id,
                         text=f"Вы выбрали услугу '{service_name}' стоимостью {price} монет."
                              f" Пожалуйста, отправьте фото выполненной работы.")
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, receive_photo,
                                                  service_id, service_name, price, type,
                                                  call.from_user.id)

    else:
        bot.send_message(chat_id=call.message.chat.id, text="Ошибка: услуга не найдена.")


def receive_photo(message, service_id, service_name, price, type, seller_id):
    if message.content_type == 'photo':
        bot.send_message(chat_id=message.chat.id, text="Фото получено. Ожидайте подтверждения.")
        logging.debug(f"report: {service_id, service_name, price, type, seller_id}")

        send_confirmation_request(message.chat.id, service_id, seller_id, price, service_name, type)
    else:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, отправьте фото выполненной работы.")


def send_confirmation_request(chat_id, service_id, seller_id, price, service_name, type):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Подтвердить выполнение",
                                    callback_data=f"confirm_{service_id}_{seller_id}_{price}_{service_name}_{type}"))
    bot.send_message(chat_id=chat_id, text="Подтвердите выполнение задачи:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_'))
def confirm_task(call):
    service = call.data.split('_')
    service_id, task_user_id, price, service_name, type = service[1], service[2], service[3], service[4], service[5]
    logging.debug(f"callback data: {service}")
    if call.from_user.id != int(task_user_id):
        session = create_connection()
        session.execute(text("UPDATE accounts SET balance = balance - :price WHERE user_id = 0"), {'price': price})
        session.execute(text("UPDATE accounts SET balance = balance + :price WHERE user_id = :task_user_id"),
                        {'price': price, 'task_user_id': task_user_id})
        session.execute(text("INSERT INTO completed_services (user_id, service_name, price, type, status, end_date)"
                             " VALUES (:user_id, :service_name, :price, :type, :status, :end_date)"),
                        {'user_id': task_user_id,
                         'service_name': service_name,
                         'price': price,
                         'type': type,
                         'status': 'closed',
                         'end_date': datetime.now().strftime("%Y-%m-%d %H:%M")
                         }
                        )
        session.commit()
        session.close()
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text="Пользователь успешно закончил дело.")
    else:
        bot.answer_callback_query(call.id, "Вы не можете подтвердить выполнение своей задачи.")


@bot.message_handler(commands=['debts'])
def show_debts(message):
    session = create_connection()
    loans = session.execute(text("SELECT user_id, amount, start_date, interest_rate FROM loans "
                                 "WHERE status = 'active'")).fetchall()
    session.close()

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


@bot.message_handler(commands=['send'])
def send_money(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Банк", callback_data="send_bank"))
    session = create_connection()
    users = session.execute(text("SELECT user_id FROM accounts WHERE user_id != 0")).fetchall()
    session.close()
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
        session = create_connection()
        user_balance = session.execute(text("SELECT balance FROM accounts "
                                            "WHERE user_id = :user_id"), {'user_id': user_id}).fetchone()[0]
        if user_balance >= amount:
            session.execute(text("UPDATE accounts SET balance = balance - :amount WHERE user_id = :user_id"),
                            {'amount': amount, 'user_id': user_id}
                            )
            if recipient_id == "bank":
                session.execute(text("UPDATE accounts SET balance = balance + :amount WHERE user_id = 0"),
                                {'amount', amount}
                                )
            else:
                session.execute(text("UPDATE accounts SET balance = balance + :amount WHERE user_id = :user_id"),
                                {'amount': amount, 'user_id': int(recipient_id)}
                                )
            session.commit()
            recipient_name = "банк" if recipient_id == "bank" else recipient_id
            bot.send_message(chat_id=message.chat.id, text=f"Вы успешно отправили {amount} монет {recipient_name}.")
        else:
            bot.send_message(chat_id=message.chat.id, text="У вас недостаточно средств для отправки этой суммы.")
        session.close()
    except ValueError:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, введите корректную сумму.")


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
        message_text = message.text
        service_name, price = message_text.split(',')
        price = float(price.strip())
        session = create_connection()
        session.execute(
            text(
                "INSERT INTO services (service_name, price, type) VALUES (:service_name, :price, :type)"
            ),
            {'service_name': service_name.strip(), 'price': price, 'type': category}
        )
        session.commit()
        session.close()
        bot.send_message(chat_id=message.chat.id,
                         text=f"Услуга '{service_name.strip()}' стоимостью {price} монет "
                              f"успешно добавлена в категорию {category}.")
    except ValueError:
        bot.send_message(chat_id=message.chat.id,
                         text="Пожалуйста, введите корректное название и "
                              "стоимость услуги в формате: название, стоимость.")


# Обработчик команды /remove_service
@bot.message_handler(commands=['remove_service'])
def remove_service(message):
    session = create_connection()
    services = session.execute(text("SELECT service_id, service_name FROM services")).fetchall()
    session.close()
    markup = InlineKeyboardMarkup()
    for service in services:
        service_id, service_name = service
        markup.add(InlineKeyboardButton(f"{service_name}", callback_data=f"remove_{service_id}"))
    bot.reply_to(message, "Выберите услугу для удаления:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_'))
def handle_remove_service(call):
    service_id = int(call.data.split('_')[1])
    session = create_connection()
    session.execute(text("DELETE FROM services WHERE service_id = :service_id"),
                    {'service_id': service_id}
                    )
    session.commit()
    session.close()
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(chat_id=call.message.chat.id, text="Услуга успешно удалена.")


@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "Добро пожаловать! Вот список доступных команд и их описание:\n\n"
        "/start - Начало работы с ботом. Создает ваш аккаунт в системе, если его еще нет.\n\n"
        "/loan - Выберите сумму кредита, которую хотите взять, или погасите существующий кредит."
        " Вы не можете взять новый кредит, пока не погасите текущий.\n\n"
        "/balance - Показывает баланс вашего счета и счета других пользователей.\n\n"
        "/change_balance - Изменяет баланс выбранного пользователя, нужно подтверждение другого пользователя.\n\n"
        "/buy - Показывает список доступных услуг для покупки.\n\n"
        "/sell - Показывает список услуг, которые вы можете оказать.\n\n"
        "/debts - Показывает текущие долги пользователей, включая накопленные проценты и "
        "время до следующего увеличения долга.\n\n"
        "/send - Отправить деньги другому пользователю или банку. Выберите получателя и введите сумму."
        " Если у вас недостаточно средств, операция будет отменена.\n\n"
        "/add_service - Добавить новую услугу в категорию 'buy' или 'sell'."
        " Сначала выберите категорию, затем введите название услуги и"
        " ее стоимость в формате: \"Имя услуги, стоимость\".\n\n"
        "/remove_service - Удалить услугу.\n\n"
        "/transactions - История выполненных услуг.\n\n"
        "/waiting_list - Выберите пользователя и просмотрите его список дел."
        "Для завершения задачи необходимо подтверждение от другого пользователя.\n\n"
        "Дополнительная информация:\n\n"
        "Со всех buy операций 25% идет в банк, кроме Экспресс услуг, за них 100% идет банку."
    )
    bot.reply_to(message, help_text)


@bot.message_handler(commands=['waiting_list'])
def show_waiting_list(message):
    markup = InlineKeyboardMarkup()
    session = create_connection()
    users = session.execute(text("SELECT user_id FROM accounts WHERE user_id != 0")).fetchall()
    session.close()
    for user in users:
        user_id = user[0]
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
    session = create_connection()
    tasks = session.execute(text("SELECT service_id, service_name FROM completed_services "
                            "WHERE user_id = :user_id AND status = :status"),
                            {'user_id': user_id, 'status': 'active'}).fetchall()
    session.close()
    markup = InlineKeyboardMarkup()
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    if tasks:
        for task in tasks:
            service_id, service_name = task
            markup.add(InlineKeyboardButton(service_name, callback_data=f"task_{service_id}_{user_id}"))
        bot.send_message(chat_id=call.message.chat.id, text="Список дел пользователя:", reply_markup=markup)
    else:
        bot.send_message(chat_id=call.message.chat.id, text="У пользователя нет дел.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('task_'))
def handle_task(call):
    service_id, task_user_id = call.data.split('_')[1], call.data.split('_')[2]
    if call.from_user.id != int(task_user_id):
        session = create_connection()
        session.execute(text("UPDATE completed_services SET status = :status, end_date = :end_date"
                             " WHERE service_id = :service_id"),
                        {'status': 'closed',
                         'end_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
                         'service_id': service_id
                         }
                        )
        session.commit()
        session.close()
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text="Дело успешно закончено.")
    else:
        bot.answer_callback_query(call.id, "Вы не можете удалить свое собственное дело.")


@bot.message_handler(commands=['transactions'])
def show_transactions(message):
    session = create_connection()
    transactions = session.execute(text("""
        SELECT 
            a.user_id,
            a.service_name,
            a.type,
            a.price,
            strftime('%Y-%m-%d %H:%M', a.end_date) as closed_date
        FROM completed_services a
        JOIN accounts b ON a.user_id = b.user_id
        WHERE a.status = 'closed'
    """)).fetchall()
    session.close()

    if transactions:
        transactions_text = "Завершенные услуги:\n"
        for transaction in transactions:
            user_id = transaction[0]
            service_name = transaction[1]
            service_type = transaction[2]
            closed_date = transaction[4]

            try:
                user_info = bot.get_chat_member(chat_id=message.chat.id, user_id=user_id).user
                user_name = user_info.first_name
                if user_info.last_name:
                    user_name += f" {user_info.last_name}"
            except ApiTelegramException:
                user_name = f"Пользователь {user_id}"

            transactions_text += f"{user_name}, {service_name}, {service_type}, {closed_date}\n"
    else:
        transactions_text = "Нет завершенных услуг"

    bot.reply_to(message, transactions_text)


def update_loans():
    while True:
        session = create_connection()
        loans = session.execute(text("SELECT loan_id, user_id, amount, start_date, interest_rate FROM loans"
                             " WHERE status = 'active'")).fetchall()
        for loan in loans:
            loan_id, user_id, amount, start_date, interest_rate = loan
            start_date = datetime.strptime(start_date, "%Y-%m-%d")
            now = datetime.now()
            elapsed_time = now - start_date

            if amount <= 12:
                if elapsed_time > timedelta(hours=24):
                    new_interest_rate = interest_rate + 0.25 * (
                            (elapsed_time - timedelta(hours=24)) // timedelta(hours=24) + 1)
                    session.execute(text("UPDATE loans SET status = 'closed' WHERE loan_id = :loan_id"),
                                    {'loan_id': loan_id}
                                    )
                    session.execute(text(
                        "INSERT INTO loans (user_id, amount, start_date, interest_rate, status)"
                        " VALUES (:user_id, :amount, :start_date, :interest_rate, 'active')"),
                        {'user_id': user_id,
                         'amount': amount,
                         'start_date': now.strftime("%Y-%m-%d"),
                         'interest_rate': new_interest_rate
                         }
                    )
            else:
                if elapsed_time > timedelta(hours=48):
                    new_interest_rate = interest_rate + 0.25 * (
                            (elapsed_time - timedelta(hours=48)) // timedelta(hours=72) + 1)
                    session.execute(text("UPDATE loans SET status = 'closed' WHERE loan_id = :loan_id"),
                                    {'loan_id': loan_id})
                    session.execute(text(
                        "INSERT INTO loans (user_id, amount, start_date, interest_rate, status)"
                        " VALUES (:user_id, :amount, :start_date, :interest_rate, 'active')"),
                        {'user_id': user_id,
                         'amount': amount,
                         'start_date': now.strftime("%Y-%m-%d"),
                         'interest_rate': new_interest_rate
                         }
                    )
        session.commit()
        session.close()
        time.sleep(60)


loan_thread = threading.Thread(target=update_loans)
loan_thread.start()

bot.polling()
