import argparse
import csv
import html
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from email.message import EmailMessage
from pathlib import Path


NEWS_API_URL = "https://newsapi.org/v2/top-headlines"


def required_env(name):
	value = os.environ.get(name, "").strip()
	if not value:
		raise ValueError(f"Set the {name} environment variable first.")
	return value


def fetch_articles(api_key, country, category):
	parameters = {"apiKey": api_key, "country": country, "pageSize": 10}
	if category:
		parameters["category"] = category
	url = f"{NEWS_API_URL}?{urllib.parse.urlencode(parameters)}"
	request = urllib.request.Request(url, headers={"User-Agent": "DailyNewsNewsletter/1.0"})
	try:
		with urllib.request.urlopen(request, timeout=20) as response:
			payload = json.load(response)
	except urllib.error.HTTPError as error:
		raise RuntimeError(f"News API request failed (HTTP {error.code}).") from None
	except urllib.error.URLError as error:
		raise RuntimeError(f"Could not reach the News API: {error.reason}") from None

	if payload.get("status") != "ok":
		raise RuntimeError(f"News API error: {payload.get('message', 'unknown error')}")
	return payload.get("articles", [])


def read_recipients(csv_path):
	recipients = set()
	with csv_path.open(newline="", encoding="utf-8-sig") as audience_file:
		reader = csv.DictReader(audience_file)
		if not reader.fieldnames or not {"email", "subscribed"}.issubset(reader.fieldnames):
			raise ValueError("Audience CSV must have 'email' and 'subscribed' columns.")
		for row in reader:
			if (row.get("subscribed") or "").strip().lower() not in {"yes", "true", "1"}:
				continue
			address = (row.get("email") or "").strip()
			if "@" in address and "\n" not in address and "\r" not in address:
				recipients.add(address)
	if not recipients:
		raise ValueError("No subscribed email addresses were found in the audience CSV.")
	return sorted(recipients)


def render_newsletter(articles, country):
	text_items = []
	html_items = []
	for article in articles:
		title = str(article.get("title") or "Untitled")
		description = str(article.get("description") or "")
		link = str(article.get("url") or "")
		source = str((article.get("source") or {}).get("name") or "News")
		published = str(article.get("publishedAt") or "")

		text_items.append(f"{title}\n{source} | {published}\n{description}\n{link}")
		html_items.append(
			"<article>"
			f"<h2><a href=\"{html.escape(link, quote=True)}\">{html.escape(title)}</a></h2>"
			f"<p><strong>{html.escape(source)}</strong> | {html.escape(published)}</p>"
			f"<p>{html.escape(description)}</p>"
			"</article>"
		)

	date_label = date.today().strftime("%B %d, %Y")
	text_body = f"Daily news for {country.upper()} - {date_label}\n\n" + "\n\n".join(text_items)
	html_body = (
		"<!doctype html><html><body>"
		f"<h1>Daily news - {country.upper()}</h1><p>{html.escape(date_label)}</p>"
		+ "".join(html_items)
		+ "</body></html>"
	)
	return text_body, html_body


def send_newsletter(recipients, articles, country):
	smtp_host = required_env("SMTP_HOST")
	smtp_username = required_env("SMTP_USERNAME")
	smtp_password = required_env("SMTP_PASSWORD")
	email_from = required_env("EMAIL_FROM")
	smtp_port = int(os.environ.get("SMTP_PORT", "587"))
	text_body, html_body = render_newsletter(articles, country)

	with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
		server.ehlo()
		server.starttls(context=ssl.create_default_context())
		server.login(smtp_username, smtp_password)
		for recipient in recipients:
			message = EmailMessage()
			message["Subject"] = f"Daily News - {country.upper()}"
			message["From"] = email_from
			message["To"] = recipient
			message.set_content(text_body)
			message.add_alternative(html_body, subtype="html")
			server.send_message(message)
			print(f"Sent to {recipient}")


def main():
	parser = argparse.ArgumentParser(description="Email a daily news digest to subscribed readers.")
	parser.add_argument("--dry-run", action="store_true", help="Fetch and preview news without sending email.")
	args = parser.parse_args()

	api_key = required_env("NEWS_API_KEY")
	country = os.environ.get("NEWS_COUNTRY", "us").strip().lower()
	category = os.environ.get("NEWS_CATEGORY", "").strip().lower()
	articles = fetch_articles(api_key, country, category)
	if not articles:
		raise ValueError("The News API returned no articles; no email was sent.")

	if args.dry_run:
		text_body, _ = render_newsletter(articles, country)
		print(text_body)
		return 0

	csv_path = Path(os.environ.get("AUDIENCE_CSV", Path(__file__).with_name("audience.csv")))
	recipients = read_recipients(csv_path)
	send_newsletter(recipients, articles, country)
	return 0


if __name__ == "__main__":
	try:
		raise SystemExit(main())
	except (OSError, ValueError, RuntimeError, smtplib.SMTPException) as error:
		print(f"Newsletter failed: {error}", file=sys.stderr)
		raise SystemExit(1) from None
