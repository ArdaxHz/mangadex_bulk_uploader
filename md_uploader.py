import json
import logging
import re
import sys
import time
from typing import Optional, Tuple
import zipfile
from datetime import date
from pathlib import Path

import requests
from natsort import natsorted
from dotenv import dotenv_values

uuid_regex = re.compile(r'[0-9a-fA-F]{8}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{12}')
file_name_regex = re.compile(r'^(?:\[(?P<artist>.+?)?\])?\s?(?P<title>.+?)(?:\s?\[(?P<language>[a-zA-Z]+)?\])?\s?-\s?(?P<prefix>(?:[c](?:h(?:a?p?(?:ter)?)?)?\.?\s?))?(?P<chapter>\d+(?:\.\d)?)?(?:\s?\((?:[v](?:ol(?:ume)?(?:s)?)?\.?\s?)?(?P<volume>\d+(?:\.\d)?)?\))?\s?(?:\((?P<chapter_title>.+)\))?\s?(?:\[(?:(?P<group>.+))?\])?\s?(?:\{v?(?P<version>\d)?\})?(?:\.(?P<extension>zip|cbz))?$', re.IGNORECASE)
languages = [{"english":"English","md":"en","iso":"eng"},{"english":"Japanese","md":"ja","iso":"jpn"},{"english":"Japanese (Romaji)","md":"ja-ro","iso":"jpn"},{"english":"Polish","md":"pl","iso":"pol"},{"english":"Serbo-Croatian","md":"sh","iso":"hrv"},{"english":"Dutch","md":"nl","iso":"dut"},{"english":"Italian","md":"it","iso":"ita"},{"english":"Russian","md":"ru","iso":"rus"},{"english":"German","md":"de","iso":"ger"},{"english":"Hungarian","md":"hu","iso":"hun"},{"english":"French","md":"fr","iso":"fre"},{"english":"Finnish","md":"fi","iso":"fin"},{"english":"Vietnamese","md":"vi","iso":"vie"},{"english":"Greek","md":"el","iso":"gre"},{"english":"Bulgarian","md":"bg","iso":"bul"},{"english":"Spanish (Es)","md":"es","iso":"spa"},{"english":"Portuguese (Br)","md":"pt-br","iso":"por"},{"english":"Portuguese (Pt)","md":"pt","iso":"por"},{"english":"Swedish","md":"sv","iso":"swe"},{"english":"Arabic","md":"ar","iso":"ara"},{"english":"Danish","md":"da","iso":"dan"},{"english":"Chinese (Simp)","md":"zh","iso":"chi"},{"english":"Chinese (Romaji)","md":"zh-ro","iso":"chi"},{"english":"Bengali","md":"bn","iso":"ben"},{"english":"Romanian","md":"ro","iso":"rum"},{"english":"Czech","md":"cs","iso":"cze"},{"english":"Mongolian","md":"mn","iso":"mon"},{"english":"Turkish","md":"tr","iso":"tur"},{"english":"Indonesian","md":"id","iso":"ind"},{"english":"Korean","md":"ko","iso":"kor"},{"english":"Korean (Romaji)","md":"ko-ro","iso":"kor"},{"english":"Spanish (LATAM)","md":"es-la","iso":"spa"},{"english":"Persian","md":"fa","iso":"per"},{"english":"Malay","md":"ms","iso":"may"},{"english":"Thai","md":"th","iso":"tha"},{"english":"Catalan","md":"ca","iso":"cat"},{"english":"Filipino","md":"tl","iso":"fil"},{"english":"Chinese (Trad)","md":"zh-hk","iso":"chi"},{"english":"Ukrainian","md":"uk","iso":"ukr"},{"english":"Burmese","md":"my","iso":"bur"},{"english":"Lithuanian","md":"lt","iso":"lit"},{"english":"Hebrew","md":"he","iso":"heb"},{"english":"Hindi","md":"hi","iso":"hin"},{"english":"Norwegian","md":"no","iso":"nor"},{"english":"Other","md":"NULL","iso":"NULL"}]
http_error_codes = {"400": "Bad request.", "401": "Unauthorised.", "403": "Forbidden.", "404": "Not found.", "429": "Too many requests."}
md_api_url = 'https://api.mangadex.org'
md_upload_api_url = f'{md_api_url}/upload'

root_path = Path('.')
log_folder_path = root_path.joinpath('logs')
log_folder_path.mkdir(parents=True, exist_ok=True)

logs_path = log_folder_path.joinpath(
    f'md_uploader_{str(date.today())}.log')
logging.basicConfig(
    filename=logs_path,
    level=logging.DEBUG,
    format='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S')


def get_lang_md(language: str) -> str:
    """Convert the inputted language into the format MangaDex uses

    Args:
        language (str): Can be the full language name, ISO 639-2 or ISO 639-3 codes.

    Returns:
        str: ISO 639-2 code, which MangaDex uses for languages.
    """

    # Chapter language is English
    if language is None:
        return "en"
    elif language.lower() in ("eng", "en"):
        return "en"
    elif len(language) < 2:
        logging.warning(f'Language selected, {language} isn\'t in ISO format.')
        print('Not a valid language option.')
        return "NULL"
    # Chapter language already in correct format for MD
    elif re.match(r'^[a-zA-Z\-]{2,5}$', language):
        logging.info(f'Language {language} already in ISO-639-2 form.')
        return language
    # Language in iso-639-3 format already
    elif len(language) == 3:
        available_langs = [l["md"] for l in languages if l["iso"] == language]

        if available_langs:
            return available_langs[0]
        return "NULL"
    else:
        # Language is a word instead of code, look for language and use that code
        languages_match = [l for l in languages if language.lower() in l["english"].lower()]

        if len(languages_match) > 1:
            print("Found multiple matching languages, please choose the language you want to download from the following options.")

            for count, item in enumerate(languages_match, start=1):
                print(f'{count}: {item["english"]}')

            try:
                lang = int(input(f'Choose a number matching the position of the language: '))
            except ValueError:
                logging.warning('Language option selected is not a number, using NULL as language.')
                print("That's not a number.")
                return "NULL"

            if lang not in range(1, (len(languages_match) + 1)):
                logging.warning('Language option selected is not in the accepted range.')
                print('Not a valid language option.')
                return "NULL"

            lang_to_use = languages_match[(lang - 1)]
            return lang_to_use["md"]

        return languages_match[0]["md"]


def remove_upload_session(session: requests.Session, upload_session_id: str):
    """Delete the upload session."""
    session.delete(f'{md_upload_api_url}/{upload_session_id}')
    logging.info(f'Sent session {upload_session_id} to be deleted.')


def print_error(error_response: requests.Response) -> str:
    """Print the errors the site returns."""
    status_code = error_response.status_code
    error_converting_json_log_message = "{} when converting error_response into json."
    error_converting_json_print_message = f"{status_code}: Couldn't convert api reposnse into json."
    error_message = ''

    if status_code == 429:
        error_message = f'429: {http_error_codes.get(str(status_code))}'
        logging.error(error_message)
        print(error_message)
        time.sleep(4)
        return error_message

    # Api didn't return json object
    try:
        error_json = error_response.json()
    except json.JSONDecodeError as e:
        logging.error(error_converting_json_log_message.format(e))
        print(error_converting_json_print_message)
        return error_converting_json_print_message
    # Maybe already a json object
    except AttributeError:
        logging.error(f"error_response is already a json.")
        # Try load as a json object
        try:
            error_json = json.loads(error_response.content)
        except json.JSONDecodeError as e:
            logging.error(error_converting_json_log_message.format(e))
            print(error_converting_json_print_message)
            return error_converting_json_print_message

    # Api response doesn't follow the normal api error format
    try:
        errors = [
            f'{e["status"]}: {e["detail"] if e["detail"] is not None else ""}' for e in error_json["errors"]]
        errors = ', '.join(errors)

        if not errors:
            errors = http_error_codes.get(str(status_code), '')

        error_message = f'Error: {errors}.'
        logging.warning(error_message)
        print(error_message)
    except KeyError:
        error_message = f'KeyError: {status_code}.'
        logging.warning(error_message)
        print(error_message)

    return error_message


def process_zip(to_upload: Path, names_to_ids: dict) -> Optional[Tuple[Optional[str]]]:
    """Get the chapter data from the file name."""

    # Check if the zip name is in the correct format
    zip_name_match = file_name_regex.match(to_upload.name)
    if not zip_name_match:
        logging.error(f"Zip {to_upload.name} isn't in the correct naming format.")
        print(f'{to_upload.name} not in the correct naming format, skipping.')
        return

    # Get the series title, use id map if zip file doesn't have the uuid already
    manga_series = zip_name_match.group("title")
    if not uuid_regex.match(manga_series):
        try:
            manga_series = names_to_ids["manga"].get(manga_series, None)
        except KeyError:
            manga_series = None
            logging.warning(f'No manga id found for {manga_series}.')

    language = get_lang_md(zip_name_match.group("language"))

    chapter_number = zip_name_match.group("chapter")
    if chapter_number is not None:
        parts = re.split('\.|\-', chapter_number)
        parts[0] = '0' if len(parts[0].lstrip(
            '0')) == 0 else parts[0].lstrip('0')

        chapter_number = '.'.join(parts)

    # Chapter is a oneshot
    if zip_name_match.group("prefix") is None:
        chapter_number = None
        logging.info('No chapter number prefix found, uploading as oneshot.')

    volume_number = zip_name_match.group("volume")
    if volume_number is not None:
        volume_number = volume_number.lstrip('0')
        # Volume 0
        if len(volume_number) == 0:
            volume_number = '0'

    chapter_title = zip_name_match.group("chapter_title")
    if chapter_title is not None:
        # Add the question mark back to the chapter title
        chapter_title = chapter_title.replace('<question_mark>', '?')

    groups = []
    groups_match = zip_name_match.group("group")
    if groups_match is not None:
        # Split the zip name groups into an array and remove any leading/trailing whitespace 
        groups_array = groups_match.split('+')
        groups_array = [g.strip() for g in groups_array]

        # Check if the groups are using uuids, if not, use the id map for the id
        for group in groups_array:
            if not uuid_regex.match(group):
                try:
                    group_id = names_to_ids["group"].get(group, None)
                except KeyError:
                    logging.warning(f'No group id found for {group}, not tagging the upload with this group.')
                    group_id = None
                if group_id is not None:
                    groups.append(group_id)
            else:
                groups.append(group)

    upload_details = f'Manga id: {manga_series}, chapter: {chapter_number}, volume: {volume_number}, title: {chapter_title}, language: {language}, groups: {groups}.'
    logging.info(f'Chapter upload details: {upload_details}')
    print(upload_details)
    return (manga_series, language, chapter_number, volume_number, groups, chapter_title)


def login_to_md(env_values: dict, session: requests.Session):
    """Login to MangaDex using the credentials found in the env file."""
    username = env_values["MANGADEX_USERNAME"]
    password = env_values["MANGADEX_PASSWORD"]
    login_response = session.post(f'{md_api_url}/auth/login', json={"username": username, "password": password})

    if login_response.status_code != 200:
        error = print_error(login_response)
        logging.critical(f"Couldn't login. Error: {error}")
        raise Exception("Couldn't login.")

    # Update requests session with headers to always be logged in
    session_token = login_response.json()["token"]["session"]
    session.headers.update({"Authorization": f"Bearer {session_token}"})


def open_manga_series_map(env_values: dict, files_path: Path) -> dict:
    """Get the manga-name-to-id map."""
    try:
        with open(files_path.joinpath(env_values["NAME_ID_MAP_FILE"]).with_suffix('.json'), 'r') as json_file:
            names_to_ids = json.load(json_file)
    except FileNotFoundError:
        not_found_error = f"The manga name-to-id json file couldn't be found. Continuing with an empty name-id map."
        logging.error(not_found_error)
        print(not_found_error)
        return {"manga":{}, "group":{}}
    except json.JSONDecodeError:
        corrupted_error = f"The manga name-to-id json file is corrupted. Continuing with an empty name-id map."
        logging.error(corrupted_error)
        print(corrupted_error)
        return {"manga":{}, "group":{}}
    return names_to_ids


def load_env_file(root_path: Path) -> dict:
    """Read the data from the env if it exists."""
    env_file_path = root_path.joinpath('.env')
    if not env_file_path.exists():
        logging.critical('.env file not found.')
        raise Exception(f"Couldn't find env file.")

    env_dict = dotenv_values(env_file_path)
    if env_dict["MANGADEX_USERNAME"] == '' or env_dict["MANGADEX_PASSWORD"] == '':
        logging.critical('No mangadex login details provided.')
        raise Exception(f'Missing login details.')

    try:
        env_dict["NUMBER_OF_IMAGES_UPLOAD"] = int(env_dict["NUMBER_OF_IMAGES_UPLOAD"])
    except ValueError:
        logging.warning('.env file number of images to upload is empty or contains a non-number character, using default of 10.')
        env_dict["NUMBER_OF_IMAGES_UPLOAD"] = 10

    try:
        env_dict["UPLOAD_RETRY"] = int(env_dict["UPLOAD_RETRY"])
    except ValueError:
        logging.warning('.env file number of image retry is empty or contains a non-number character, using default of 10.')
        env_dict["UPLOAD_RETRY"] = 3

    return env_dict


if __name__ == "__main__":

    env_values = load_env_file(root_path)
    names_to_ids = open_manga_series_map(env_values, root_path)
    to_upload_folder_path = Path(env_values["UPLOADS_FOLDER"])
    uploaded_files_path = Path(env_values["UPLOADED_FILES"])
    images_upload_session = int(env_values["NUMBER_OF_IMAGES_UPLOAD"])
    number_upload_retry = int(env_values["UPLOAD_RETRY"])
    zips_to_upload = [x for x in to_upload_folder_path.iterdir() if x.suffix in ('.zip', '.cbz')]
    zips_to_not_upload = [x for x in to_upload_folder_path.iterdir() if x.suffix not in ('.zip', '.cbz')]

    logging.warning(f'Skipping zips {zips_to_not_upload}')

    if not zips_to_upload:
        logging.info('No zips found for upload, exiting.')
        sys.exit(0)

    session = requests.Session()
    login_to_md(env_values, session)
    group_fallback = [] if env_values["GROUP_FALLBACK_ID"] == '' else [env_values["GROUP_FALLBACK_ID"]]
    failed_uploads = []

    for to_upload in zips_to_upload:
        zip_name = to_upload.name
        zip_extension = to_upload.suffix
        # Only accept zip files
        if zip_extension not in ('.zip', '.cbz'):
            logging.error(f"{to_upload} doesn't have the correct extension, skipping.")
            continue

        values = process_zip(to_upload, names_to_ids)
        if values is None:
            logging.error(f"No values processed from {to_upload}, skipping.")
            continue

        manga_series, language, chapter_number, volume_number, groups, chapter_title = values
        if not groups:
            logging.info('Zip groups array is empty, using group fallback.')
            print(f'No groups found, using group fallback.')
            groups = group_fallback
            if not groups:
                logging.info('Group fallback not found, uploading without a group.')
                print('Group fallback not found, uploading without a group.')

        if manga_series is None:
            logging.error(f"Couldn't find a manga id for {zip_name}, skipping.")
            print(f'Skipped {zip_name}, no manga id found.')
            continue

        # Remove any exising upload sessions to not error out
        existing_session = session.get(f'{md_upload_api_url}')
        if existing_session.status_code == 200:
            logging.info(f'Upload session found, deleting it.')
            remove_upload_session(session, existing_session.json()["data"]["id"])

        # Start the upload session
        upload_session_response = session.post(f'{md_upload_api_url}/begin', json={"manga": manga_series, "groups": groups})
        if upload_session_response.status_code != 200:
            error = print_error(upload_session_response)
            logging.error(f"Couldn't create upload draft for {zip_name}. Error: {error}")
            print(f'Error creating draft for {zip_name}.')
            continue

        upload_session_id = upload_session_response.json()["data"]["id"]
        upload_session_id_message = f'Created upload session: {upload_session_id}, {zip_name}.'
        logging.info(upload_session_id_message)
        print(upload_session_id_message)

        image_ids = []
        failed_image_upload = False
        # Open zip file and read the data
        with zipfile.ZipFile(to_upload) as myzip:
            info_list = myzip.infolist()
            # Remove any directories and none-image files from the zip info array
            info_list_images_only = [image.filename for image in info_list if (not image.is_dir() and Path(image.filename).suffix in ('.png', '.jpg', '.jpeg', '.gif'))]
            info_list_images_only = natsorted(info_list_images_only)
            logging.info(f'Images to upload: {info_list_images_only}')
            # Separate the image array into smaller arrays of 5 images
            info_list_separate = [info_list_images_only[l:l + images_upload_session] for l in range(0, len(info_list_images_only), images_upload_session)]

            for array_index, images in enumerate(info_list_separate, start=1):
                files = {}
                image_new_names = {}
                # Read the image data and add to files dict
                for image_index, image in enumerate(images, start=1):
                    image_filename = str(Path(image).name)
                    renamed_file = str(info_list_images_only.index(image))
                    image_new_names.update({renamed_file: image_filename})
                    with myzip.open(image) as myfile:
                        files.update({renamed_file: myfile.read()})

                image_retries = 0
                while image_retries < number_upload_retry:
                    # Upload the images
                    image_upload_response = session.post(f'{md_upload_api_url}/{upload_session_id}', files=files)
                    if image_upload_response.status_code != 200:
                        error = print_error(image_upload_response)
                        logging.error(f"Error uploading images. Error: {error}")
                        failed_image_upload = True
                        image_retries += 1
                        time.sleep(2)
                        continue

                    # Some images returned errors
                    uploaded_image_data = image_upload_response.json()
                    succesful_upload_data = uploaded_image_data["data"]
                    if uploaded_image_data["errors"] or uploaded_image_data["result"] == 'error':
                        error = print_error(image_upload_response)
                        logging.warning(f"Image errored out. Error: {error}")

                    # Add successful image uploads to the image ids array
                    for uploaded_image in succesful_upload_data:
                        uploaded_image_attributes = uploaded_image["attributes"]
                        original_filename = uploaded_image_attributes["originalFileName"]
                        file_size = uploaded_image_attributes["fileSize"]
                        image_ids.insert(int(original_filename), uploaded_image["id"])
                        succesful_upload_message = f'Success: Uploaded page {image_new_names[original_filename]}, size: {file_size} bytes.'
                        logging.info(succesful_upload_message)
                        print(succesful_upload_message)

                    if len(succesful_upload_data) == len(files):
                        failed_image_upload = False
                        image_retries == number_upload_retry
                        logging.info('Uploaded all images.')
                        break
                    else:
                        files = {k:v for (k, v) in files.items() if k not in [i["attributes"]["originalFileName"] for i in succesful_upload_data]}
                        logging.warning(f"Some images didn't upload, retrying. Failed images: {files}")
                        failed_image_upload = True
                        image_retries += 1
                        time.sleep(2)
                        continue

                if failed_image_upload:
                    break

                # Rate limit
                if array_index % 5 == 0:
                    time.sleep(3)

        # Skip chapter upload and delete upload session
        if failed_image_upload:
            failed_image_upload_message = f'Deleting draft due to failed image upload: {upload_session_id}, {zip_name}.'
            print(failed_image_upload_message)
            logging.error(failed_image_upload_message)
            remove_upload_session(session, upload_session_id)
            failed_uploads.append(to_upload)
            continue

        # Try to commit the chapter 3 times
        commit_retries = 0
        succesful_upload = False
        while commit_retries < number_upload_retry:
            chapter_commit_response = session.post(f'{md_upload_api_url}/{upload_session_id}/commit',
                json={"chapterDraft":
                    {"volume": volume_number, "chapter": chapter_number, "title": chapter_title, "translatedLanguage": language}, "pageOrder": image_ids
                })

            if chapter_commit_response.status_code == 200:
                succesful_upload = True
                succesful_upload_id = chapter_commit_response.json()["data"]["id"]
                print(f'Succesfully uploaded: {succesful_upload_id}, {zip_name}.')
                logging.info(f"Succesful commit: {succesful_upload_id}, {zip_name}.")

                # Move the uploaded zips to a different folder
                uploaded_files_path.mkdir(parents=True, exist_ok=True)
                to_upload.rename(uploaded_files_path.joinpath(zip_name).with_suffix(zip_extension))
                commit_retries == number_upload_retry
                break

            print_error(chapter_commit_response)
            commit_fail_message = f'Failed to commit {zip_name}, error {chapter_commit_response.status_code} trying again.'
            logging.warning(commit_fail_message)
            print(commit_fail_message)
            commit_retries += 1
            time.sleep(1)

        if not succesful_upload:
            commit_error_message = f'Failed to commit {zip_name}, removing upload draft.'
            logging.error(commit_error_message)
            print(commit_error_message)
            remove_upload_session(session, upload_session_id)
            failed_uploads.append(to_upload)

        time.sleep(3)

    if failed_uploads:
        logging.info(f'Failed uploads: {failed_uploads}')
        print(f'Failed uploads:')
        for fail in failed_uploads:
            print(fail)
