# handlers/payment.py
from telegram import Update, LabeledPrice
from telegram.ext import ContextTypes, CommandHandler, PreCheckoutQueryHandler, MessageHandler, filters
from database.db import update_user_field, get_user
from datetime import datetime, timedelta
import json

VIP_PLANS = {
    'monthly': {'stars': 150, 'days': 30, 'label': 'VIP Monthly'},
    'yearly': {'stars': 1200, 'days': 365, 'label': 'VIP Yearly'},
}

async def vip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)

    if user and user['is_vip']:
        expires = user['vip_expires']
        await update.message.reply_text(
            f"💎 You're already VIP until {expires[:10]}.\n\n"
            "VIP Benefits:\n"
            "• Unlimited video processing\n"
            "• Priority queue (faster results)\n"
            "• Access to community voice/video chat\n"
            "• Visible profile to other VIP members\n"
            "• Save unlimited vocabulary lists"
        )
        return

    text = (
        "💎 <b>Upgrade to VIP</b>\n\n"
        "Free plan: 2 videos/day, basic features\n\n"
        "VIP Benefits:\n"
        "• ♾️ Unlimited videos\n"
        "• ⚡ Priority processing\n"
        "• 🎙 Join voice/video practice rooms\n"
        "• 👥 Connect with other learners\n"
        "• 📊 Progress tracking & spaced repetition\n\n"
        "Choose a plan:\n"
        "/buy_monthly - 150 ⭐ (~$3/month)\n"
        "/buy_yearly - 1200 ⭐ (~$24/year)"
    )
    await update.message.reply_text(text, parse_mode='HTML')


async def buy_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_key: str):
    plan = VIP_PLANS[plan_key]

    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=plan['label'],
        description=f"Unlock VIP features for {plan['days']} days",
        payload=json.dumps({'plan': plan_key, 'user_id': update.effective_user.id}),
        provider_token="",  # empty string for Telegram Stars (XTR)
        currency="XTR",
        prices=[LabeledPrice(plan['label'], plan['stars'])],
    )


async def buy_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_plan(update, context, 'monthly')


async def buy_yearly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_plan(update, context, 'yearly')


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # Always answer within 10 seconds
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = json.loads(payment.invoice_payload)
    plan_key = payload['plan']
    user_id = update.effective_user.id

    plan = VIP_PLANS[plan_key]

    user = get_user(user_id)
    current_expiry = user.get('vip_expires')
    if current_expiry and datetime.fromisoformat(current_expiry) > datetime.now():
        new_expiry = datetime.fromisoformat(current_expiry) + timedelta(days=plan['days'])
    else:
        new_expiry = datetime.now() + timedelta(days=plan['days'])

    update_user_field(user_id, 'is_vip', 1)
    update_user_field(user_id, 'vip_expires', new_expiry.isoformat())

    # Log payment
    from database.db import get_conn
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO payments (user_id, amount, currency, status, provider_payment_id, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, payment.total_amount, payment.currency, 'completed',
         payment.telegram_payment_charge_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎉 Payment successful! You're now VIP until {new_expiry.strftime('%Y-%m-%d')}.\n\n"
        "Try /find_partner to connect with other learners!"
    )


def get_payment_handlers():
    return [
        CommandHandler('vip', vip_handler),
        CommandHandler('buy_monthly', buy_monthly),
        CommandHandler('buy_yearly', buy_yearly),
        PreCheckoutQueryHandler(precheckout_callback),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback),
    ]