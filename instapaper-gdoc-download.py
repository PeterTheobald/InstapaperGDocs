import os
import json
import argparse
from requests_oauthlib import OAuth1Session
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

"""
Instapaper-gdoc-download.py
Scans an Instapaper folder and downloads all of the Google Docs linked in the bookmarks
"""

# Load configuration from external file
with open("config.json", "r") as config_file:
    config = json.load(config_file)

# Instapaper and Google API credentials
INSTAPAPER_CONSUMER_KEY = config["INSTAPAPER_CONSUMER_KEY"]
INSTAPAPER_CONSUMER_SECRET = config["INSTAPAPER_CONSUMER_SECRET"]
INSTAPAPER_USERNAME = config["INSTAPAPER_USERNAME"]
INSTAPAPER_PASSWORD = config["INSTAPAPER_PASSWORD"]
GOOGLE_CREDENTIALS_PATH = config["GOOGLE_CREDENTIALS_PATH"]

GOOGLE_API_SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
GOOGLE_AUTHORIZED_USER_PATH = "google-authorized-user.json"


def get_instapaper_access_token():
    """Obtain OAuth access token using xAuth."""
    url = "https://www.instapaper.com/api/1/oauth/access_token"
    oauth = OAuth1Session(
        INSTAPAPER_CONSUMER_KEY, client_secret=INSTAPAPER_CONSUMER_SECRET
    )
    data = {
        "x_auth_username": INSTAPAPER_USERNAME,
        "x_auth_password": INSTAPAPER_PASSWORD,
        "x_auth_mode": "client_auth",
    }
    response = oauth.post(url, data=data)
    if response.status_code == 200:
        token_data = dict(item.split("=") for item in response.text.split("&"))
        return token_data["oauth_token"], token_data["oauth_token_secret"]
    else:
        raise Exception(f"Failed to get access token: {response.text}")


def authenticate_instapaper(oauth_token, oauth_token_secret):
    """Authenticate with Instapaper using OAuth."""
    return OAuth1Session(
        INSTAPAPER_CONSUMER_KEY,
        client_secret=INSTAPAPER_CONSUMER_SECRET,
        resource_owner_key=oauth_token,
        resource_owner_secret=oauth_token_secret,
    )


def generate_google_authorized_user():
    flow = InstalledAppFlow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_PATH, GOOGLE_API_SCOPES
    )
    creds = flow.run_local_server(port=0)
    with open(GOOGLE_AUTHORIZED_USER_PATH, "w") as token_file:
        token_file.write(creds.to_json())
    return creds


def download_gdoc(doc_url: str, title: str, save_folder: str, creds):
    """Download Google Doc to current directory"""
    try:
        # Extract the document ID from the URL
        doc_id = doc_url.split("/d/")[1].split("/")[0]

        # Build the Drive API service
        service = build("drive", "v3", credentials=creds)

        # Set the desired export MIME type (Word document)
        mime_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        request = service.files().export_media(fileId=doc_id, mimeType=mime_type)

        # Define the output file path
        output_file_path = os.path.join(save_folder, f"{title}.docx")

        # Download the file
        with open(output_file_path, "wb") as file_handle:
            downloader = MediaIoBaseDownload(file_handle, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                print(f"Download progress: {int(status.progress() * 100)}%")

        print(f"Google Doc downloaded successfully as '{output_file_path}'")
        return output_file_path

    except Exception as e:
        print(f"Error downloading Google Doc: {e}")
        return None


def fetch_google_doc_info(doc_url, creds):
    """Retrieve information about a Google Doc."""
    doc_id = doc_url.split("/d/")[1].split("/")[0]
    GDriveService = build("drive", "v3", credentials=creds)
    # TODO: Find out if building a service is expensive, and if so do this once and reuse

    try:
        # Get file metadata
        file_metadata = (
            GDriveService.files()
            .get(fileId=doc_id, fields="name, owners(displayName), modifiedTime")
            .execute()
        )

        # Extract required details
        name = file_metadata.get("name")
        owner = file_metadata.get("owners", [{}])[0].get("displayName", "Unknown")
        modified_time = file_metadata.get("modifiedTime", "Unknown")

        return {"title": name, "owner": owner, "modified_date": modified_time}

    except Exception as e:
        print(f"Error retrieving metadata: {e}")
        return None


def get_instapaper_folder_id(session, folder_name):
    """Retrieve the numerical ID of a folder given its name."""
    url = "https://www.instapaper.com/api/1.1/folders/list"
    response = session.post(url)
    if response.status_code == 200:
        folders = response.json()
        for folder in folders:
            if folder.get("type") == "folder" and folder.get("title") == folder_name:
                return folder.get("folder_id")
        return None
    else:
        raise Exception(f"Failed to fetch folders: {response.text}")


def get_instapaper_bookmarks(session, folder_name):
    """Retrieve bookmarks from a specific Instapaper folder by its name."""
    # Get the numerical ID of the folder
    folder_id = get_instapaper_folder_id(session, folder_name)
    if not folder_id:
        raise Exception(f"No such folder named {folder_name}")

    # Fetch bookmarks from the folder
    url = "https://www.instapaper.com/api/1/bookmarks/list"
    response = session.post(url, data={"folder_id": folder_id, "limit": 500})
    # TODO: handle paging more than 500 bookmarks
    if response.status_code == 200:
        response_data = response.json()
        # Filter items where "type" is "bookmark" and the URL is a Google Doc
        bookmarks = [
            item
            for item in response_data
            if item.get("type") == "bookmark"
            and "docs.google.com/document" in item.get("url", "")
        ]
        return bookmarks
    else:
        raise Exception(f"Failed to fetch bookmarks: {response.text}")


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Scan Instapaper folder for Google Docs and downloads them"
    )
    parser.add_argument(
        "folder", type=str, help="The name of the Instapaper folder to scan"
    )
    parser.add_argument(
        "save_folder",
        type=str,
        help="Destination folder to save downloaded Google Docs to",
    )
    # TODO: Add option to specify doc download destination folder
    args = parser.parse_args()

    folder = args.folder
    save_folder = args.save_folder
    print(f"Scanning folder: {folder}, downloading docs to {save_folder}")

    # Step 1: Get Instapaper OAuth tokens
    oauth_token, oauth_token_secret = get_instapaper_access_token()
    session = authenticate_instapaper(oauth_token, oauth_token_secret)

    # Step 2: Authenticate Google
    # creds = Credentials.from_authorized_user_file(GOOGLE_CREDENTIALS_PATH, GOOGLE_API_SCOPES)
    # Use the authorized user file instead of the original credentials.json
    if os.path.exists(GOOGLE_AUTHORIZED_USER_PATH):
        creds = Credentials.from_authorized_user_file(
            GOOGLE_AUTHORIZED_USER_PATH, GOOGLE_API_SCOPES
        )
    else:
        creds = generate_google_authorized_user()

    # Step 3: Fetch Instapaper bookmarks
    bookmarks = get_instapaper_bookmarks(session, folder_name=folder)

    # Step 4: Retrieve details from Google Docs and Download doc
    # Note: This always adds the author and date to the title
    # TODO: Add option to use actual title or append author and/or date
    for bookmark in bookmarks:
        # doc_info = fetch_google_doc_info(bookmark["url"], creds)
        print(f'Got {bookmark["title"]}')
        download_gdoc(bookmark["url"], bookmark["title"], save_folder, creds)


if __name__ == "__main__":
    main()
