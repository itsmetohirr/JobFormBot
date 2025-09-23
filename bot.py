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
# Load environment variables from .env if present
load_dotenv()

# Bot token: set BOT_TOKEN env var or paste here (not recommended to hardcode)
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Google Service Account JSON file path or JSON content via env
# Option 1 (recommended): set GOOGLE_SERVICE_ACCOUNT_JSON to path, e.g. "/path/to/sa.json"
# Option 2: set GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT with the full JSON content
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "PASTE_SERVICE_ACCOUNT_JSON_PATH_OR_LEAVE_EMPTY")
GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")

# Google Sheet ID and target range for appending rows
# Example sheet URL: https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "PASTE_YOUR_SHEET_ID_HERE")
# Range can be the sheet/tab name, e.g. "Sheet1!A1"
GOOGLE_SHEET_RANGE = os.getenv("GOOGLE_SHEET_RANGE", "Sheet1!A1")

# Scopes: only spreadsheets append/read
GOOGLE_SCOPES = [
	"https://www.googleapis.com/auth/spreadsheets"
]

# Admin notifications: either ADMIN_CHAT_IDS (comma-separated) or single ADMIN_CHAT_ID
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
# FSM States (Uzbek flow)
# ==========================
class ApplicationForm(StatesGroup):
	salary_expectation = State()
	prev_job_duration = State()
	criminal_record = State()
	marital_status = State()
	children_count = State()
	last_workplace = State()
	last_salary = State()
	computer_skill = State()
	languages = State()
	intended_duration = State()
	phone = State()
	photo = State()


# ==========================
# Google Sheets Helper
# ==========================

def _load_google_credentials() -> Credentials:
	"""Create Credentials from service account JSON file or content.

	Priority:
	1) GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT (JSON string)
	2) GOOGLE_SERVICE_ACCOUNT_JSON (file path)
	"""
	if GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT:
		import json
		info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT)
		return Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)

	if GOOGLE_SERVICE_ACCOUNT_JSON and os.path.exists(GOOGLE_SERVICE_ACCOUNT_JSON):
		return Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=GOOGLE_SCOPES)

	raise RuntimeError(
		"Google service account credentials not configured. Set GOOGLE_SERVICE_ACCOUNT_JSON to a valid file path or GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT to JSON content."
	)


def append_application_row(row_values: List[Any]) -> None:
	"""Append a single row to the configured Google Sheet.

	row_values order should match your sheet columns.
	"""
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
	"🤩 SIZNI QADRLAYDIGAN JAMOAGA QO‘SHILISHNI XOHLAYSIZMI?\n\n"
	"✨ Ish mazmuni: \n\n"
	"— Mijozlar bilan muloqot qilish\n"
	"— Mahsulot haqida ma’lumot berish\n"
	"— Mahsulotlarni sotish\n"
	"— Ma’lumotlarni bazaga kiritish\n\n"
	"✅ Biz sizni tanlaymiz, agar:\n\n"
	"— 18-40 yosh oralig‘ida bo‘lsangiz\n"
	"— Jamoada ishlashni bilsangiz\n"
	"— E’tiborli va muzokara qila olsangiz\n"
	"— Stressga chidamli bo‘lsangiz\n"
	"— Xushmuomala va ozoda boʻlsangiz\n\n"
	"🥰 Sizni kutadigan imkoniyatlar:\n\n"
	"— Do‘stona jamoa\n"
	"— Oylik + bonuslar\n"
	"— Rasman ishga qabul qilish\n"
	"— Bepul o‘qish va tajriba\n"
	"— Karyera va rivojlanish imkoniyati\n"
	"— Haftasiga bir kun dam olish\n"
	"— Yiliga 2 marta sayohatlar\n\n"
	"⬇️ Pastdagi tugmani bosib, roʻyxatdan oʻtishni boshlang!\n\n"
	"❕Iltimos ro'yxatdan o'tishda barcha ma'lumotlaringizni aniqlik bilan kiriting."
)

VACANCY_INFO = (
	"Vacancy: Python Developer\n"
	"Location: Remote\n"
	"Schedule: Full-time\n"
	"Description: Join our team to build scalable services and great user experiences."
)

REGISTER_BUTTON_TEXT = "📝 Ro'yxatdan o'tish"


# ==========================
# Keyboards
# ==========================

def contact_request_keyboard() -> ReplyKeyboardMarkup:
	return ReplyKeyboardMarkup(
		keyboard=[[KeyboardButton(text="Kontakt ulashish", request_contact=True)]],
		resize_keyboard=True,
		one_time_keyboard=True,
		input_field_placeholder="Telefon raqamingiz",
	)


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


# ==========================
# Handlers
# ==========================
@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
	# Reset any previous state and show intro with inline registration button attached to the same message
	await state.clear()
	await message.answer(WELCOME_MESSAGE, reply_markup=registration_inline_keyboard())


@router.callback_query(F.data == "register")
async def on_register_callback(callback: CallbackQuery, state: FSMContext) -> None:
	await callback.answer()
	await state.set_state(ApplicationForm.salary_expectation)
	await callback.message.answer("💸 Qancha maoshga ishlashni xohlaysiz?")


@router.message(Command("myid"))
async def handle_myid(message: Message) -> None:
	await message.answer(f"Your chat ID: {message.chat.id}")


@router.message(ApplicationForm.salary_expectation)
async def q_salary_expectation(message: Message, state: FSMContext) -> None:
	await state.update_data(salary_expectation=(message.text or "").strip())
	await state.set_state(ApplicationForm.prev_job_duration)
	await message.answer("💼 Oldingi ish joyingizda qancha muddat ishlagansiz?")


@router.message(ApplicationForm.prev_job_duration)
async def q_prev_duration(message: Message, state: FSMContext) -> None:
	await state.update_data(prev_job_duration=(message.text or "").strip())
	await state.set_state(ApplicationForm.criminal_record)
	await message.answer("⚖️ Sudlanganmisiz? Ha / Yoʻq", reply_markup=yes_no_keyboard())


@router.message(ApplicationForm.criminal_record, F.text.in_({"Ha", "Yo'q", "Yoʻq", "yo'q", "yoʻq"}))
async def q_criminal_record(message: Message, state: FSMContext) -> None:
	text = (message.text or "").strip()
	value = "Ha" if text.lower().startswith("h") else "Yo'q"
	await state.update_data(criminal_record=value)
	await state.set_state(ApplicationForm.marital_status)
	await message.answer("💍 Oilaviy holatingiz qanday?\n\n— Turmush qurganmisiz?\n— Farzandingiz bormi, soni nechta?", reply_markup=ReplyKeyboardRemove())


@router.message(ApplicationForm.criminal_record)
async def q_criminal_record_free(message: Message, state: FSMContext) -> None:
	await state.update_data(criminal_record=(message.text or "").strip())
	await state.set_state(ApplicationForm.marital_status)
	await message.answer("💍 Oilaviy holatingiz qanday?\n\n— Turmush qurganmisiz?\n— Farzandingiz bormi, soni nechta?", reply_markup=ReplyKeyboardRemove())


@router.message(ApplicationForm.marital_status)
async def q_marital_status(message: Message, state: FSMContext) -> None:
	await state.update_data(marital_status=(message.text or "").strip())
	await state.set_state(ApplicationForm.children_count)
	await message.answer("Farzandingiz bormi, soni nechta?")


@router.message(ApplicationForm.children_count)
async def q_children_count(message: Message, state: FSMContext) -> None:
	await state.update_data(children_count=(message.text or "").strip())
	await state.set_state(ApplicationForm.last_workplace)
	await message.answer("🏢 Oxirgi ish joyingiz qaysi edi?")


@router.message(ApplicationForm.last_workplace)
async def q_last_workplace(message: Message, state: FSMContext) -> None:
	await state.update_data(last_workplace=(message.text or "").strip())
	await state.set_state(ApplicationForm.last_salary)
	await message.answer("💰 Oxirgi ish joyingizda maoshingiz qancha boʻlgan?")


@router.message(ApplicationForm.last_salary)
async def q_last_salary(message: Message, state: FSMContext) -> None:
	await state.update_data(last_salary=(message.text or "").strip())
	await state.set_state(ApplicationForm.computer_skill)
	await message.answer(
		"💻 Kompyuterdan foydalanish darajangiz qanday?\n\n1️⃣ Bilmayman\n2️⃣ Boshlangʻich bilaman\n3️⃣ O‘rtacha daraja\n4️⃣ Juda ham yaxshi",
		reply_markup=computer_skill_keyboard(),
	)


@router.message(ApplicationForm.computer_skill)
async def q_computer_skill(message: Message, state: FSMContext) -> None:
	text = (message.text or "").strip()
	mapping = {"1": "1", "2": "2", "3": "3", "4": "4", "1️⃣": "1", "2️⃣": "2", "3️⃣": "3", "4️⃣": "4"}
	value = mapping.get(text, text)
	await state.update_data(computer_skill=value)
	await state.set_state(ApplicationForm.languages)
	await message.answer("💡 Qaysi tillarni, qanday darajada bilasiz?", reply_markup=ReplyKeyboardRemove())


@router.message(ApplicationForm.languages)
async def q_languages(message: Message, state: FSMContext) -> None:
	await state.update_data(languages=(message.text or "").strip())
	await state.set_state(ApplicationForm.intended_duration)
	await message.answer("🏥 Yangi ish joyingizda qancha muddat ishlashni rejalashtiryapsiz?")


@router.message(ApplicationForm.intended_duration)
async def q_intended_duration(message: Message, state: FSMContext) -> None:
	await state.update_data(intended_duration=(message.text or "").strip())
	await state.set_state(ApplicationForm.phone)
	await message.answer("☎️ Telefon raqamingizni yuboring!", reply_markup=contact_request_keyboard())


@router.message(ApplicationForm.phone, F.content_type == ContentType.CONTACT)
async def q_phone_contact(message: Message, state: FSMContext) -> None:
	phone = message.contact.phone_number if message.contact else (message.text or "").strip()
	await state.update_data(phone=phone)
	await state.set_state(ApplicationForm.photo)
	await message.answer("🖼️ Iltimos anketa uchun, o'zingizning rasmingizni yuboring!", reply_markup=ReplyKeyboardRemove())


@router.message(ApplicationForm.phone)
async def q_phone_text(message: Message, state: FSMContext) -> None:
	await state.update_data(phone=(message.text or "").strip())
	await state.set_state(ApplicationForm.photo)
	await message.answer("🖼️ Iltimos anketa uchun, o'zingizning rasmingizni yuboring!")


@router.message(ApplicationForm.photo, F.photo)
async def q_photo(message: Message, state: FSMContext) -> None:
	photo_sizes = message.photo or []
	file_id = photo_sizes[-1].file_id if photo_sizes else ""
	await _finalize_and_save(message, state, file_id)


@router.message(ApplicationForm.photo)
async def q_photo_fallback(message: Message, state: FSMContext) -> None:
	await _finalize_and_save(message, state, (message.text or "").strip())


async def _finalize_and_save(message: Message, state: FSMContext, photo_file_id: str) -> None:
	await state.update_data(photo_file_id=photo_file_id)
	data = await state.get_data()

	row = [
		datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
		str(message.from_user.id if message.from_user else ""),
		(message.from_user.username if message.from_user and message.from_user.username else ""),
		data.get("salary_expectation", ""),
		data.get("prev_job_duration", ""),
		data.get("criminal_record", ""),
		data.get("marital_status", ""),
		data.get("children_count", ""),
		data.get("last_workplace", ""),
		data.get("last_salary", ""),
		data.get("computer_skill", ""),
		data.get("languages", ""),
		data.get("intended_duration", ""),
		data.get("phone", ""),
		data.get("photo_file_id", ""),
	]

	write_ok = True
	try:
		append_application_row(row)
	except Exception as exc:  # noqa: BLE001
		write_ok = False
		logging.exception("Failed to append to Google Sheet: %s", exc)
		await message.answer(
			"Arizangiz qabul qilindi, ammo Google Sheetsa saqlashda xatolik yuz berdi. Administrator xabardor qilindi."
		)
	else:
		await message.answer(
			"✅ Tabriklayman!\n\n— Arizangiz muvaffaqiyatli qabul qilindi. Yuborgan anketangizni albatta koʻrib chiqamiz va sizga aloqaga chiqamiz!",
		)

	if ADMIN_CHAT_IDS:
		user_id = message.from_user.id if message.from_user else None
		username = f"@{message.from_user.username}" if (message.from_user and message.from_user.username) else "(no username)"
		status_text = "Saved to Google Sheet" if write_ok else "FAILED to save to Google Sheet"
		admin_text = (
			"Yangi anketa keldi:\n"
			f"Time (UTC): {row[0]}\n"
			f"User ID: {user_id}\n"
			f"Username: {username}\n"
			f"💸 Xohl. maosh: {data.get('salary_expectation','')}\n"
			f"💼 Oldingi muddat: {data.get('prev_job_duration','')}\n"
			f"⚖️ Sudlanganmi: {data.get('criminal_record','')}\n"
			f"💍 Oilaviy: {data.get('marital_status','')}\n"
			f"👶 Farzandlar: {data.get('children_count','')}\n"
			f"🏢 Oxirgi ish joyi: {data.get('last_workplace','')}\n"
			f"💰 Oxirgi maosh: {data.get('last_salary','')}\n"
			f"💻 Komp. daraja: {data.get('computer_skill','')}\n"
			f"💡 Tillar: {data.get('languages','')}\n"
			f"🏥 Yangi ishda muddat: {data.get('intended_duration','')}\n"
			f"☎️ Telefon: {data.get('phone','')}\n"
			f"🖼️ Photo file_id: {data.get('photo_file_id','')}\n"
			f"Status: {status_text}"
		)
		for admin_chat_id in ADMIN_CHAT_IDS:
			try:
				await message.bot.send_message(chat_id=admin_chat_id, text=admin_text)
			except Exception as notify_exc:  # noqa: BLE001
				logging.exception("Failed to notify admin %s: %s", admin_chat_id, notify_exc)

	await state.clear()


# ==========================
# Entry point
# ==========================
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
