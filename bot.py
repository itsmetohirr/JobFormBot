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
# Range can be the sheet/tab name, e.g. "Applications" or "Applications!A1"
GOOGLE_SHEET_RANGE = os.getenv("GOOGLE_SHEET_RANGE", "Applications!A1")

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
# FSM States
# ==========================
class ApplicationForm(StatesGroup):
	full_name = State()
	birthdate = State()
	address = State()
	experience = State()
	salary = State()
	phone = State()


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
		# Fallback if the provided range cannot be parsed (e.g., missing sheet/tab)
		if "Unable to parse range" in str(http_err):
			# Try using only the sheet/tab name before '!'
			sheet_name = GOOGLE_SHEET_RANGE.split("!", 1)[0]
			_append_with_range(sheet_name)
		else:
			raise


# ==========================
# Bot and Router
# ==========================
router = Router()

WELCOME_MESSAGE = (
	"Welcome to Our Company!\n\n"
	"We're excited to learn more about you."
)

VACANCY_INFO = (
	"Vacancy: Python Developer\n"
	"Location: Remote\n"
	"Schedule: Full-time\n"
	"Description: Join our team to build scalable services and great user experiences."
)


# ==========================
# Keyboards
# ==========================

def contact_request_keyboard() -> ReplyKeyboardMarkup:
	return ReplyKeyboardMarkup(
		keyboard=[[KeyboardButton(text="Share Contact", request_contact=True)]],
		resize_keyboard=True,
		one_time_keyboard=True,
		input_field_placeholder="Please share your phone number",
	)


# ==========================
# Handlers
# ==========================
@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
	# Show company's welcome message
	await message.answer(WELCOME_MESSAGE)
	# Send vacancy information first
	await message.answer(VACANCY_INFO)
	# Begin questionnaire
	await state.set_state(ApplicationForm.full_name)
	await message.answer("Please enter your Full Name (Name Surname):")


@router.message(Command("myid"))
async def handle_myid(message: Message) -> None:
	await message.answer(f"Your chat ID: {message.chat.id}")


@router.message(ApplicationForm.full_name, F.text.len() > 1)
async def handle_full_name(message: Message, state: FSMContext) -> None:
	await state.update_data(full_name=message.text.strip())
	await state.set_state(ApplicationForm.birthdate)
	await message.answer("Enter your Birthdate (e.g., 1995-08-21):")


@router.message(ApplicationForm.birthdate)
async def handle_birthdate(message: Message, state: FSMContext) -> None:
	text = (message.text or "").strip()
	# Attempt simple validation: accept YYYY-MM-DD or DD.MM.YYYY
	parsed: Optional[str] = None
	for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
		try:
			dt = datetime.strptime(text, fmt)
			parsed = dt.strftime("%Y-%m-%d")
			break
		except ValueError:
			continue

	if not parsed:
		await message.answer("Invalid date format. Please use YYYY-MM-DD or DD.MM.YYYY:")
		return

	await state.update_data(birthdate=parsed)
	await state.set_state(ApplicationForm.address)
	await message.answer("Enter your Address (City, Country):")


@router.message(ApplicationForm.address, F.text.len() > 1)
async def handle_address(message: Message, state: FSMContext) -> None:
	await state.update_data(address=message.text.strip())
	await state.set_state(ApplicationForm.experience)
	await message.answer("Briefly describe your Work Experience:")


@router.message(ApplicationForm.experience, F.text.len() > 1)
async def handle_experience(message: Message, state: FSMContext) -> None:
	await state.update_data(experience=message.text.strip())
	await state.set_state(ApplicationForm.salary)
	await message.answer("What are your Salary Expectations? (specify currency)")


@router.message(ApplicationForm.salary, F.text.len() > 0)
async def handle_salary(message: Message, state: FSMContext) -> None:
	await state.update_data(salary=message.text.strip())
	await state.set_state(ApplicationForm.phone)
	await message.answer(
		"Please share your Phone Number using the button below or type it manually:",
		reply_markup=contact_request_keyboard(),
	)


@router.message(ApplicationForm.phone, F.content_type == ContentType.CONTACT)
async def handle_phone_contact(message: Message, state: FSMContext) -> None:
	if not message.contact:
		await message.answer("Please use the 'Share Contact' button or type your phone number.")
		return
	phone = message.contact.phone_number
	await _finalize_and_save(message, state, phone)


@router.message(ApplicationForm.phone, F.text.len() > 3)
async def handle_phone_text(message: Message, state: FSMContext) -> None:
	# Minimal sanitation for phone input
	phone = message.text.strip()
	await _finalize_and_save(message, state, phone)


async def _finalize_and_save(message: Message, state: FSMContext, phone: str) -> None:
	await state.update_data(phone=phone)
	data = await state.get_data()

	# Prepare row: timestamp, user_id, username, data fields
	row = [
		datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
		str(message.from_user.id if message.from_user else ""),
		(message.from_user.username if message.from_user and message.from_user.username else ""),
		data.get("full_name", ""),
		data.get("birthdate", ""),
		data.get("address", ""),
		data.get("experience", ""),
		data.get("salary", ""),
		data.get("phone", ""),
	]

	# Attempt to write to Google Sheet
	write_ok = True
	try:
		append_application_row(row)
	except Exception as exc:  # noqa: BLE001
		write_ok = False
		logging.exception("Failed to append to Google Sheet: %s", exc)
		await message.answer(
			"Your application was received, but saving to Google Sheet failed. "
			"An administrator will review this issue."
		)
	else:
		await message.answer(
			"Thank you! Your application has been recorded.",
			reply_markup=ReplyKeyboardRemove(),
		)

	# Notify admins
	if ADMIN_CHAT_IDS:
		user_id = message.from_user.id if message.from_user else None
		username = f"@{message.from_user.username}" if (message.from_user and message.from_user.username) else "(no username)"
		status_text = "Saved to Google Sheet" if write_ok else "FAILED to save to Google Sheet"
		admin_text = (
			"New application received:\n"
			f"Time (UTC): {row[0]}\n"
			f"User ID: {user_id}\n"
			f"Username: {username}\n"
			f"Full Name: {data.get('full_name','')}\n"
			f"Birthdate: {data.get('birthdate','')}\n"
			f"Address: {data.get('address','')}\n"
			f"Experience: {data.get('experience','')}\n"
			f"Salary: {data.get('salary','')}\n"
			f"Phone: {data.get('phone','')}\n"
			f"Status: {status_text}"
		)
		for admin_chat_id in ADMIN_CHAT_IDS:
			try:
				await message.bot.send_message(chat_id=admin_chat_id, text=admin_text)
			except Exception as notify_exc:  # noqa: BLE001
				logging.exception("Failed to notify admin %s: %s", admin_chat_id, notify_exc)

	# Reset state after finishing
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
