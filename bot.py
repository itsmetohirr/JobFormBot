import asyncio
import logging
import os
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
	CallbackQuery,
	ContentType,
	KeyboardButton,
	Message,
	ReplyKeyboardMarkup,
	ReplyKeyboardRemove,
	InlineKeyboardMarkup,
	InlineKeyboardButton,
	User,
)
from aiogram.client.default import DefaultBotProperties

# --- Google Sheets API (placeholders and setup) ---
# Requires: google-api-python-client, google-auth, google-auth-httplib2, google-auth-oauthlib
# Install: pip install google-api-python-client google-auth
from google.oauth2.service_account import Credentials  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
from dotenv import load_dotenv


# ==========================
# Configuration (placeholders)
# ==========================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "PASTE_SERVICE_ACCOUNT_JSON_PATH_OR_LEAVE_EMPTY")
GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "PASTE_YOUR_SHEET_ID_HERE")
GOOGLE_SHEET_RANGE = os.getenv("GOOGLE_SHEET_RANGE", "Sheet1!A1")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_ADMIN_IDS_RAW = os.getenv("ADMIN_CHAT_IDS", "").strip()
_ADMIN_ID_SINGLE = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_IDS: List[int] = []
if _ADMIN_IDS_RAW:
	for part in _ADMIN_IDS_RAW.split(","):
		part = part.strip()
		if part:
			try:
				ADMIN_CHAT_IDS.append(int(part))
			except ValueError:
				logging.warning("Ignoring invalid ADMIN_CHAT_IDS entry: %s", part)
elif _ADMIN_ID_SINGLE:
	try:
		ADMIN_CHAT_IDS = [int(_ADMIN_ID_SINGLE)]
	except ValueError:
		logging.warning("Invalid ADMIN_CHAT_ID value: %s", _ADMIN_ID_SINGLE)


# ==========================
# FSM States (New 11-step flow)
# ==========================
class ApplicationForm(StatesGroup):
	full_name = State()                       # 1
	birthdate = State()                       # 2
	address = State()                         # 3
	desired_region = State()                  # 4
	education_level = State()                 # 5
	total_experience_duration = State()       # 6
	prev_job_duration_and_place = State()     # 7
	marital_status = State()                  # 8 (includes spouse/children details)
	salary_expectation = State()              # 9
	computer_skill = State()                  # 10
	phone = State()                           # 11


# ==========================
# Google Sheets Helper
# ==========================

def _load_google_credentials() -> Credentials:
	if GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT:
		import json
		info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT)
		return Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)
	if GOOGLE_SERVICE_ACCOUNT_JSON and os.path.exists(GOOGLE_SERVICE_ACCOUNT_JSON):
		return Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=GOOGLE_SCOPES)
	raise RuntimeError("Google service account credentials not configured. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT.")


def append_application_row(row_values: List[Any]) -> None:
	if not GOOGLE_SHEET_ID or "PASTE_YOUR_SHEET_ID_HERE" in GOOGLE_SHEET_ID:
		raise RuntimeError("GOOGLE_SHEET_ID is not set. Please configure it.")
	creds = _load_google_credentials()
	service = build("sheets", "v4", credentials=creds)
	sheets = service.spreadsheets()
	body = {"values": [row_values]}
	def _append_with_range(target_range: str) -> None:
		sheets.values().append(
			spreadsheetId=GOOGLE_SHEET_ID,
			range=target_range,
			valueInputOption="USER_ENTERED",
			insertDataOption="INSERT_ROWS",
			body=body,
		).execute()
	try:
		_append_with_range(GOOGLE_SHEET_RANGE)
	except HttpError as http_err:
		if "Unable to parse range" in str(http_err):
			sheet_name = GOOGLE_SHEET_RANGE.split("!", 1)[0]
			_append_with_range(sheet_name + "!A1")
		else:
			raise


# ==========================
# Bot and Router
# ==========================
router = Router()

WELCOME_MESSAGE = (
	"🤩 HURMATLI FARMATSEVT! SIZNI QADRLAYDIGAN JAMOAGA QO'SHILISHNI XOHLAYSIZMI?\n\n"
	"✨ Ish mazmuni: \n\n"
	"— Mijozlar bilan muloqot qilish\n"
	"— Dori-darmonlarni sotish\n"
	"— Kompyuterdan foydalanish tajribasi\n"
	"— Dori-darmonlar haqida ma'lumot berish\n\n"
	"✅ Biz sizni tanlaymiz, agar:\n\n"
	"— 18-35 yosh oralig'ida bo'lsangiz\n"
	"— Jamoada ishlashni bilsangiz\n"
	"— E'tiborli va muzokara qila olsangiz\n"
	"— Stressga chidamli bo'lsangiz\n"
	"— Xushmuomala va ozoda boʻlsangiz\n\n"
	"🥰 Sizni kutadigan imkoniyatlar:\n\n"
	"— Do'stona jamoa\n"
	"— Oylik + bonuslar\n"
	"— Rasman ishga qabul qilish\n"
	"— Bepul o'qish va tajriba\n"
	"— Karyera va rivojlanish imkoniyati\n"
	"— Haftasiga bir kun dam olish\n"
	"— Yiliga 2 marta sayohatlar\n\n"
	"⬇️ Pastdagi tugmani bosib, roʻyxatdan oʻtishni boshlang!\n\n"
	"❕Iltimos ro'yxatdan o'tishda barcha ma'lumotlaringizni aniqlik bilan kiriting."
)

REGISTER_BUTTON_TEXT = "📝 Ro'yxatdan o'tish"


def yes_no_keyboard() -> ReplyKeyboardMarkup:
	return ReplyKeyboardMarkup(
		keyboard=[[KeyboardButton(text="Ha"), KeyboardButton(text="Yo'q")]],
		resize_keyboard=True,
		one_time_keyboard=True,
	)


def computer_skill_keyboard() -> ReplyKeyboardMarkup:
	return ReplyKeyboardMarkup(
		keyboard=[[KeyboardButton(text="1️⃣"), KeyboardButton(text="2️⃣"), KeyboardButton(text="3️⃣"), KeyboardButton(text="4️⃣")]],
		resize_keyboard=True,
		one_time_keyboard=True,
		input_field_placeholder="1 - 4 dan birini tanlang",
	)


def registration_inline_keyboard() -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		inline_keyboard=[[InlineKeyboardButton(text=REGISTER_BUTTON_TEXT, callback_data="register")]]
	)


def confirmation_inline_keyboard() -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		inline_keyboard=[[InlineKeyboardButton(text="Tasdiqlash", callback_data="confirm")]]
	)


# ==========================
# Handlers
# ==========================
@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
	await state.clear()
	await message.answer(WELCOME_MESSAGE, reply_markup=registration_inline_keyboard())


@router.callback_query(F.data == "register")
async def on_register_callback(callback: CallbackQuery, state: FSMContext) -> None:
	await callback.answer()
	await state.set_state(ApplicationForm.full_name)
	await callback.message.answer("👤 Ism-sharifingizni yozing:")


@router.callback_query(F.data == "confirm")
async def on_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
	await callback.answer()
	await _finalize_and_save(callback.message, state, actor_user=callback.from_user)


@router.message(Command("myid"))
async def handle_myid(message: Message) -> None:
	await message.answer(f"Your chat ID: {message.chat.id}")


@router.message(ApplicationForm.full_name)
async def s1_full_name(message: Message, state: FSMContext) -> None:
	await state.update_data(full_name=(message.text or "").strip())
	await state.set_state(ApplicationForm.birthdate)
	await message.answer("🗓️ Tugʻilgan kun/oy/yilni yozing:")


@router.message(ApplicationForm.birthdate)
async def s2_birthdate(message: Message, state: FSMContext) -> None:
	await state.update_data(birthdate=(message.text or "").strip())
	await state.set_state(ApplicationForm.address)
	await message.answer("📍 Yashash manzilingizni batafsil yozing.")


@router.message(ApplicationForm.address)
async def s3_address(message: Message, state: FSMContext) -> None:
	await state.update_data(address=(message.text or "").strip())
	await state.set_state(ApplicationForm.desired_region)
	await message.answer("🏥 Ishlashni xohlagan hududingizni yozing:")


@router.message(ApplicationForm.desired_region)
async def s4_desired_region(message: Message, state: FSMContext) -> None:
	await state.update_data(desired_region=(message.text or "").strip())
	await state.set_state(ApplicationForm.education_level)
	await message.answer("🎓 Maʼlumotingizni yozing!\n— Oliy yoki oʻrta maxsus:")


@router.message(ApplicationForm.education_level)
async def s5_education(message: Message, state: FSMContext) -> None:
	await state.update_data(education_level=(message.text or "").strip())
	await state.set_state(ApplicationForm.total_experience_duration)
	await message.answer("⏳ Sohadagi umumiy tajribangiz muddati qancha?")


@router.message(ApplicationForm.total_experience_duration)
async def s6_total_exp(message: Message, state: FSMContext) -> None:
	await state.update_data(total_experience_duration=(message.text or "").strip())
	await state.set_state(ApplicationForm.prev_job_duration_and_place)
	await message.answer("💼 Oldingi ish joyingizda qancha muddat ishlagansiz va u qayer edi?")


@router.message(ApplicationForm.prev_job_duration_and_place)
async def s7_prev_duration_place(message: Message, state: FSMContext) -> None:
	await state.update_data(prev_job_duration_and_place=(message.text or "").strip())
	await state.set_state(ApplicationForm.marital_status)
	await message.answer("💍 Oilaviy holatingiz qanday?\n\n— Turmush qurganmisiz?\n— Farzandingiz bormi, soni nechta?")


@router.message(ApplicationForm.marital_status)
async def s8_marital(message: Message, state: FSMContext) -> None:
	await state.update_data(marital_status=(message.text or "").strip())
	await state.set_state(ApplicationForm.salary_expectation)
	await message.answer("💸 Qancha maoshga ishlashni xohlaysiz?")


@router.message(ApplicationForm.salary_expectation)
async def s9_salary(message: Message, state: FSMContext) -> None:
	await state.update_data(salary_expectation=(message.text or "").strip())
	await state.set_state(ApplicationForm.computer_skill)
	await message.answer(
		"💻 Kompyuterdan foydalanish darajangiz qanday?\n\n1️⃣ Bilmayman\n2️⃣ Boshlangʻich bilaman\n3️⃣ O‘rtacha daraja\n4️⃣ Juda ham yaxshi",
		reply_markup=computer_skill_keyboard(),
	)


@router.message(ApplicationForm.computer_skill)
async def s10_computer_skill(message: Message, state: FSMContext) -> None:
	text = (message.text or "").strip()
	mapping = {"1": "1", "2": "2", "3": "3", "4": "4", "1️⃣": "1", "2️⃣": "2", "3️⃣": "3", "4️⃣": "4"}
	value = mapping.get(text, text)
	await state.update_data(computer_skill=value)
	await state.set_state(ApplicationForm.phone)
	await message.answer("☎️ Telefon raqamingizni yuboring!\n\n➡️ Namuna: 998 33 210 03 03", reply_markup=ReplyKeyboardRemove())


@router.message(ApplicationForm.phone)
async def s11_phone(message: Message, state: FSMContext) -> None:
	await state.update_data(phone=(message.text or "").strip())
	await _show_confirmation(message, state)


async def _show_confirmation(message: Message, state: FSMContext) -> None:
	data = await state.get_data()
	confirmation_text = (
		"Ma'lumotlar to'g'riligini tasdiqlang.\n\n"
		f"👤 Ism: {data.get('full_name', '')}\n"
		f"🗓️ Tug'ilgan sana: {data.get('birthdate', '')}\n"
		f"📍 Manzil: {data.get('address', '')}\n"
		f"🏥 Xohlagan hudud: {data.get('desired_region', '')}\n"
		f"🎓 Ma'lumoti: {data.get('education_level', '')}\n"
		f"⏳ Umumiy tajriba: {data.get('total_experience_duration', '')}\n"
		f"💼 Oldingi ish va muddat: {data.get('prev_job_duration_and_place', '')}\n"
		f"💍 Oilaviy: {data.get('marital_status', '')}\n"
		f"💸 Xohlagan maosh: {data.get('salary_expectation', '')}\n"
		f"💻 Komp. daraja: {data.get('computer_skill', '')}\n"
		f"☎️ Telefon: {data.get('phone', '')}"
	)
	await message.answer(confirmation_text, reply_markup=confirmation_inline_keyboard())


async def _finalize_and_save(message: Message, state: FSMContext, actor_user: Optional[User] | None = None) -> None:
	data = await state.get_data()
	user_obj = actor_user if actor_user is not None else message.from_user
	row = [
		datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
		str(user_obj.id if user_obj else ""),
		(user_obj.username if user_obj and user_obj.username else ""),
		data.get("full_name", ""),
		data.get("birthdate", ""),
		data.get("address", ""),
		data.get("desired_region", ""),
		data.get("education_level", ""),
		data.get("total_experience_duration", ""),
		data.get("prev_job_duration_and_place", ""),
		data.get("marital_status", ""),
		data.get("salary_expectation", ""),
		data.get("computer_skill", ""),
		data.get("phone", ""),
	]
	write_ok = True
	try:
		append_application_row(row)
	except Exception as exc:  # noqa: BLE001
		write_ok = False
		logging.exception("Failed to append to Google Sheet: %s", exc)
		await message.answer("Arizangiz qabul qilindi, ammo Google Sheetsa saqlashda xatolik yuz berdi. Administrator xabardor qilindi.")
	else:
		await message.answer("✅ Tabriklayman!\n\n— Arizangiz muvaffaqiyatli qabul qilindi. Yuborgan anketangiz bilan albatta tanishamiz va sizga aloqaga chiqamiz!")

	if ADMIN_CHAT_IDS:
		user_id = user_obj.id if user_obj else None
		username = f"@{user_obj.username}" if (user_obj and user_obj.username) else "(no username)"
		status_text = "Saved to Google Sheet" if write_ok else "FAILED to save to Google Sheet"
		admin_text = (
			"Yangi anketa keldi:\n"
			f"Time (UTC): {row[0]}\n"
			f"User ID: {user_id}\n"
			f"Username: {username}\n"
			f"👤 Ism: {data.get('full_name','')}\n"
			f"🗓️ Tug'ilgan sana: {data.get('birthdate','')}\n"
			f"📍 Manzil: {data.get('address','')}\n"
			f"🏥 Xohlagan hudud: {data.get('desired_region','')}\n"
			f"🎓 Ma'lumoti: {data.get('education_level','')}\n"
			f"⏳ Umumiy tajriba: {data.get('total_experience_duration','')}\n"
			f"💼 Oldingi ish va muddat: {data.get('prev_job_duration_and_place','')}\n"
			f"💍 Oilaviy: {data.get('marital_status','')}\n"
			f"💸 Xohlagan maosh: {data.get('salary_expectation','')}\n"
			f"💻 Komp. daraja: {data.get('computer_skill','')}\n"
			f"☎️ Telefon: {data.get('phone','')}\n"
			f"Status: {status_text}"
		)
		for admin_chat_id in ADMIN_CHAT_IDS:
			try:
				await message.bot.send_message(chat_id=admin_chat_id, text=admin_text)
			except Exception as notify_exc:  # noqa: BLE001
				logging.exception("Failed to notify admin %s: %s", admin_chat_id, notify_exc)

	await state.clear()


async def main() -> None:
	logging.basicConfig(level=logging.INFO)
	if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
		raise RuntimeError("BOT_TOKEN is not set. Please configure the BOT_TOKEN environment variable.")
	bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
	dp = Dispatcher()
	dp.include_router(router)
	logging.info("Bot is starting...")
	await dp.start_polling(bot)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except (KeyboardInterrupt, SystemExit):
		logging.info("Bot stopped.")
