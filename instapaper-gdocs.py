import os
import json
import time
import argparse
import uuid
from requests_oauthlib import OAuth1Session
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# Load configuration from external file
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

# Instapaper and Google API credentials
INSTAPAPER_CONSUMER_KEY = config["INSTAPAPER_CONSUMER_KEY"]
INSTAPAPER_CONSUMER_SECRET = config["INSTAPAPER_CONSUMER_SECRET"]
INSTAPAPER_USERNAME = config["INSTAPAPER_USERNAME"]
INSTAPAPER_PASSWORD = config["INSTAPAPER_PASSWORD"]
GOOGLE_CREDENTIALS_PATH = config["GOOGLE_CREDENTIALS_PATH"]

GOOGLE_API_SCOPES = ['https://www.googleapis.com/auth/documents.readonly', 'https://www.googleapis.com/auth/drive.metadata.readonly']
GOOGLE_AUTHORIZED_USER_PATH = 'google-authorized-user.json'

def get_instapaper_access_token():
    """Obtain OAuth access token using xAuth."""
    url = "https://www.instapaper.com/api/1/oauth/access_token"
    oauth = OAuth1Session(
        INSTAPAPER_CONSUMER_KEY,
        client_secret=INSTAPAPER_CONSUMER_SECRET
    )
    data = {
        "x_auth_username": INSTAPAPER_USERNAME,
        "x_auth_password": INSTAPAPER_PASSWORD,
        "x_auth_mode": "client_auth"
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
        resource_owner_secret=oauth_token_secret
    )

def generate_google_authorized_user():
    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_PATH, GOOGLE_API_SCOPES)
    creds = flow.run_local_server(port=0)
    with open(GOOGLE_AUTHORIZED_USER_PATH, 'w') as token_file:
        token_file.write(creds.to_json())
    return creds

def fetch_google_doc_info(doc_url, creds):
    """Retrieve information about a Google Doc."""
    doc_id = doc_url.split('/d/')[1].split('/')[0]
    GDriveService = build('drive', 'v3', credentials=creds)
    # TODO: Find out if building a service is expensive, and if so do this once and reuse

    try:
        # Get file metadata
        file_metadata = GDriveService.files().get(
            fileId=doc_id,
            fields="name, owners(displayName), modifiedTime"
        ).execute()

        # Extract required details
        name = file_metadata.get('name')
        owner = file_metadata.get('owners', [{}])[0].get('displayName', 'Unknown')
        modified_time = file_metadata.get('modifiedTime', 'Unknown')

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
    response = session.post(url, data={"folder_id": folder_id, "limit":500})
    # TODO: handle paging more than 500 bookmarks
    if response.status_code == 200:
        response_data = response.json()
        # Filter items where "type" is "bookmark" and the URL is a Google Doc
        bookmarks = [
            item for item in response_data
            if item.get("type") == "bookmark" and "docs.google.com/document" in item.get("url", "")
        ]
        return bookmarks
    else:
        raise Exception(f"Failed to fetch bookmarks: {response.text}")

def create_instapaper_folder(session, folder_name):
    """Create a new Instapaper folder."""
    url = "https://www.instapaper.com/api/1/folders/add"
    response = session.post(url, data={"title": folder_name})
    if response.status_code == 200:
        return response.json()[0]["folder_id"]
    else:
        raise Exception(f"Failed to create folder: {response.text}")

def save_instapaper_bookmark(session, folder_id, url, title, description):
    """Save a bookmark to Instapaper."""
    api_url = "https://www.instapaper.com/api/1/bookmarks/add"
    data = {
        "url": url,
        "title": title,
        "description": description,
        "content": description,
        "folder_id": folder_id
    }
    response = session.post(api_url, data=data)
    if response.status_code != 200:
        raise Exception(f"Failed to save bookmark: {response.text}")

def generate_unique_folder_name(base_name):
    """Generate a unique folder name based on the base name."""
    unique_suffix = str(uuid.uuid4())[:4]  # Generate a short unique identifier
    return f"{base_name}-{unique_suffix}"

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Scan Instapaper folder for Google Docs and copy them in mod-time order to a new folder.")
    parser.add_argument(
        "folder_name",
        type=str,
        help="The name of the Instapaper folder to scan"
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="The name of the new Instapaper folder to create (optional)"
    )
    args = parser.parse_args()

    folder_name = args.folder_name
    new_folder_name = args.target or generate_unique_folder_name(folder_name)
    print(f"Scanning folder: {folder_name}")
    print(f"New folder name: {new_folder_name}")

    # Step 1: Get Instapaper OAuth tokens
    oauth_token, oauth_token_secret = get_instapaper_access_token()
    session = authenticate_instapaper(oauth_token, oauth_token_secret)

    # Step 2: Authenticate Google
    #creds = Credentials.from_authorized_user_file(GOOGLE_CREDENTIALS_PATH, GOOGLE_API_SCOPES)
    # Use the authorized user file instead of the original credentials.json
    if os.path.exists(GOOGLE_AUTHORIZED_USER_PATH):
        creds = Credentials.from_authorized_user_file(GOOGLE_AUTHORIZED_USER_PATH, GOOGLE_API_SCOPES)
    else:
        creds = generate_google_authorized_user()

    # Step 3: Fetch Instapaper bookmarks
    bookmarks = get_instapaper_bookmarks(session, folder_name=folder_name)

    # Step 4: Retrieve details from Google Docs
    docs_info = []
    for bookmark in bookmarks:
        doc_info = fetch_google_doc_info(bookmark['url'], creds)
        print(f'Got {bookmark["title"]} - {doc_info["owner"]} {doc_info["modified_date"][:10]}')
        doc_info["url"]=bookmark["url"]
        docs_info.append(doc_info)

    # Step 5: Sort bookmarks by modify date
    docs_info.sort(key=lambda x: x['modified_date'])

    # Step 6: Create a new Instapaper folder
    new_folder_id = get_instapaper_folder_id(session, new_folder_name)
    if not new_folder_id:
        new_folder_id = create_instapaper_folder(session, new_folder_name)

    # Step 7: Save new bookmarks
    for doc in docs_info:
        title = f"{doc['title']} - {doc['owner']} - {doc['modified_date'][:10]}"
        description = f"{doc['title']} - {doc['owner']}<br>\n{doc['modified_date'][:10]}<br>\n<a href=\"{doc['url']}\">{doc['url']}</a><br>"
        print(f'Adding {doc["modified_date"][:10]} - {doc["title"]}')
        save_instapaper_bookmark(session, new_folder_id, doc['url'], title, description)
        time.sleep(1) # delay because Instapaper adds them asynchronously sometimes out of order
        # TODO: replace sleep(1) with check for bookmark existing before moving to next one

if __name__ == "__main__":
    main()
