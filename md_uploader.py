import configparser
import json
import logging
import os
import re
import time
import zipfile

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import requests

uuid_regex = re.compile(
    r'[0-9a-fA-F]{8}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{12}')
file_name_regex = re.compile(
    r'^(?:\[(?P<artist>.+?)?\])?\s?(?P<title>.+?)(?:\s?\[(?P<language>[a-zA-Z]+)?\])?\s?-\s?(?P<prefix>(?:[c](?:h(?:a?p?(?:ter)?)?)?\.?\s?))?(?P<chapter>\d+(?:\.\d)?)?(?:\s?\((?:[v](?:ol(?:ume)?(?:s)?)?\.?\s?)?(?P<volume>\d+(?:\.\d)?)?\))?\s?(?:\((?P<chapter_title>.+)\))?\s?(?:\[(?:(?P<group>.+))?\])?\s?(?:\{v?(?P<version>\d)?\})?(?:\.(?P<extension>zip|cbz))?$',
    re.IGNORECASE)
languages = [{"english":"English","md":"en","iso":"eng"},{"english":"Japanese","md":"ja","iso":"jpn"},{"english":"Japanese (Romaji)","md":"ja-ro","iso":"jpn"},{"english":"Polish","md":"pl","iso":"pol"},{"english":"Serbo-Croatian","md":"sh","iso":"hrv"},{"english":"Dutch","md":"nl","iso":"dut"},{"english":"Italian","md":"it","iso":"ita"},{"english":"Russian","md":"ru","iso":"rus"},{"english":"German","md":"de","iso":"ger"},{"english":"Hungarian","md":"hu","iso":"hun"},{"english":"French","md":"fr","iso":"fre"},{"english":"Finnish","md":"fi","iso":"fin"},{"english":"Vietnamese","md":"vi","iso":"vie"},{"english":"Greek","md":"el","iso":"gre"},{"english":"Bulgarian","md":"bg","iso":"bul"},{"english":"Spanish (Es)","md":"es","iso":"spa"},{"english":"Portuguese (Br)","md":"pt-br","iso":"por"},{"english":"Portuguese (Pt)","md":"pt","iso":"por"},{"english":"Swedish","md":"sv","iso":"swe"},{"english":"Arabic","md":"ar","iso":"ara"},{"english":"Danish","md":"da","iso":"dan"},{"english":"Chinese (Simp)","md":"zh","iso":"chi"},{"english":"Chinese (Romaji)","md":"zh-ro","iso":"chi"},{"english":"Bengali","md":"bn","iso":"ben"},{"english":"Romanian","md":"ro","iso":"rum"},{"english":"Czech","md":"cs","iso":"cze"},{"english":"Mongolian","md":"mn","iso":"mon"},{"english":"Turkish","md":"tr","iso":"tur"},{"english":"Indonesian","md":"id","iso":"ind"},{"english":"Korean","md":"ko","iso":"kor"},{"english":"Korean (Romaji)","md":"ko-ro","iso":"kor"},{"english":"Spanish (LATAM)","md":"es-la","iso":"spa"},{"english":"Persian","md":"fa","iso":"per"},{"english":"Malay","md":"ms","iso":"may"},{"english":"Thai","md":"th","iso":"tha"},{"english":"Catalan","md":"ca","iso":"cat"},{"english":"Filipino","md":"tl","iso":"fil"},{"english":"Chinese (Trad)","md":"zh-hk","iso":"chi"},{"english":"Ukrainian","md":"uk","iso":"ukr"},{"english":"Burmese","md":"my","iso":"bur"},{"english":"Lithuanian","md":"lt","iso":"lit"},{"english":"Hebrew","md":"he","iso":"heb"},{"english":"Hindi","md":"hi","iso":"hin"},{"english":"Norwegian","md":"no","iso":"nor"},{"english":"Other","md":"NULL","iso":"NULL"}]
http_error_codes = {
    "400": "Bad request.",
    "401": "Unauthorised.",
    "403": "Forbidden.",
    "404": "Not found.",
    "429": "Too many requests."}


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


def load_config_info(config: configparser.RawConfigParser):

    if config["Paths"].get("mangadex_api_url", '') == '':
        logging.warning('Mangadex api path empty, using default.')
        config["Paths"]["mangadex_api_url"] = 'https://api.mangadex.org'

    if config["Paths"].get("name_id_map_file", '') == '':
        logging.info('Name id map_file path empty, using default.')
        config["Paths"]["name_id_map_file"] = 'name_id_map.json'

    if config["Paths"].get("uploads_folder", '') == '':
        logging.info('To upload files folder path empty, using default.')
        config["Paths"]["uploads_folder"] = 'to_upload'

    if config["Paths"].get("uploaded_files", '') == '':
        logging.info('Uploaded files folder path empty, using default.')
        config["Paths"]["uploaded_files"] = 'uploaded'

    try:
        int(config["User Set"]["number_of_images_upload"])
    except ValueError:
        logging.warning(
            'Config file number of images to upload is empty or contains a non-number character, using default of 10.')
        config["User Set"]["number_of_images_upload"] = str(10)

    try:
        int(config["User Set"]["upload_retry"])
    except ValueError:
        logging.warning(
            'Config file number of image retry is empty or contains a non-number character, using default of 3.')
        config["User Set"]["upload_retry"] = str(3)

    try:
        int(config["User Set"]["ratelimit_time"])
    except ValueError:
        logging.warning(
            'Config file time to sleep is empty or contains a non-number character, using default of 2.')
        config["User Set"]["ratelimit_time"] = str(2)


def open_config_file(root_path: Path) -> configparser.RawConfigParser:
    config_file_path = root_path.joinpath('config').with_suffix('.ini')
    # Open config file and read values
    if config_file_path.exists():
        config = configparser.RawConfigParser()
        config.read(config_file_path)
        logging.info('Loaded config file.')
    else:
        logging.critical('Config file not found, exiting.')
        raise FileNotFoundError('Config file not found.')

    load_config_info(config)
    return config


config = open_config_file(root_path)
md_api_url = config["Paths"]["mangadex_api_url"]
md_upload_api_url = f'{md_api_url}/upload'
ratelimit_time = int(config["User Set"]["ratelimit_time"])


def convert_json(response_to_convert: requests.Response) -> Optional[dict]:
    """Convert the api response into a parsable json."""
    critical_decode_error_message = "Couldn't convert mangadex api response into a json."
    try:
        converted_response = response_to_convert.json()
    except json.JSONDecodeError:
        logging.critical(critical_decode_error_message)
        print(critical_decode_error_message)
        return
    except AttributeError:
        logging.critical(
            f"Api response doesn't have load as json method, trying to load as json manually.")
        try:
            converted_response = json.loads(response_to_convert.content)
        except json.JSONDecodeError:
            logging.critical(critical_decode_error_message)
            print(critical_decode_error_message)
            return

    logging.info("Convert api response into json.")
    return converted_response


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
        time.sleep(ratelimit_time * 3)
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
        error_message = f'KeyError {status_code}: {error_json}.'
        logging.warning(error_message)
        print(error_message)

    return error_message


def make_session(headers: dict = {}) -> requests.Session:
    session = requests.Session()
    session.headers.update(headers)
    return session


def login_to_md(session: requests.Session,
                config: configparser.RawConfigParser):
    """Login to MangaDex using the credentials found in the env file."""
    username = config["MangaDex Credentials"]["mangadex_username"]
    password = config["MangaDex Credentials"]["mangadex_password"]

    if username == '' or password == '':
        critical_message = 'Login details missing.'
        logging.critical(critical_message)
        raise Exception(critical_message)

    login_response = session.post(
        f'{md_api_url}/auth/login',
        json={
            "username": username,
            "password": password})

    if login_response.status_code != 200:
        login_response_error_message = f"Couldn't login, mangadex returned an error {login_response.status_code}."
        logging.critical(login_response_error_message)
        print_error(login_response)
        raise Exception(login_response_error_message)

    # Update requests session with headers to always be logged in
    login_response_json = convert_json(login_response)
    if login_response_json is None:
        login_response_json_message = "Couldn't convert login api response into a json."
        logging.error(login_response_json_message)
        raise Exception(login_response_json_message)

    session_token = login_response_json["token"]["session"]
    session.headers.update({"Authorization": f"Bearer {session_token}"})
    logging.info(f'Logged into mangadex.')
    print('Logged in.')


def open_manga_series_map(
        config: configparser.RawConfigParser,
        files_path: Path) -> dict:
    """Get the manga-name-to-id map."""
    try:
        with open(files_path.joinpath(config["Paths"]["name_id_map_file"]), 'r') as json_file:
            names_to_ids = json.load(json_file)
    except FileNotFoundError:
        not_found_error = f"The manga name-to-id json file couldn't be found. Continuing with an empty name-id map."
        logging.error(not_found_error)
        print(not_found_error)
        return {"manga": {}, "group": {}}
    except json.JSONDecodeError:
        corrupted_error = f"The manga name-to-id json file is corrupted. Continuing with an empty name-id map."
        logging.error(corrupted_error)
        print(corrupted_error)
        return {"manga": {}, "group": {}}
    return names_to_ids


class FileProcesser:

    def __init__(self, to_upload: Path, names_to_ids: dict,
                 config: configparser.RawConfigParser) -> None:
        self._to_upload = to_upload
        self._zip_name = to_upload.name
        self._names_to_ids = names_to_ids
        self._config = config

    def _match_file_name(self) -> Optional[re.Match[str]]:
        # Check if the zip name is in the correct format
        zip_name_match = file_name_regex.match(self._zip_name)
        if not zip_name_match:
            logging.error(
                f"Zip {self._zip_name} isn't in the correct naming format.")
            print(f'{self._zip_name} not in the correct naming format, skipping.')
            return
        return zip_name_match

    def _get_manga_series(self) -> Optional[UUID]:
        # Get the series title, use id map if zip file doesn't have the uuid
        # already
        manga_series = self._zip_name_match.group("title")
        if not uuid_regex.match(manga_series):
            try:
                manga_series = self._names_to_ids["manga"].get(
                    manga_series, None)
            except KeyError:
                manga_series = None
                logging.warning(f'No manga id found for {manga_series}.')

        return manga_series

    def _get_language(self) -> str:
        """Convert the inputted language into the format MangaDex uses

        Args:
            language (str): Can be the full language name, ISO 639-2 or ISO 639-3 codes.

        Returns:
            str: ISO 639-2 code, which MangaDex uses for languages.
        """
        language = self._zip_name_match.group("language")

        # Chapter language is English
        if language is None:
            return "en"
        elif language.lower() in ("eng", "en"):
            return "en"
        elif len(language) < 2:
            logging.warning(
                f'Language selected, {language} isn\'t in ISO format.')
            print('Not a valid language option.')
            return "NULL"
        # Chapter language already in correct format for MD
        elif re.match(r'^[a-zA-Z\-]{2,5}$', language):
            logging.info(f'Language {language} already in ISO-639-2 form.')
            return language
        # Language in iso-639-3 format already
        elif len(language) == 3:
            available_langs = [l["md"]
                               for l in languages if l["iso"] == language]

            if available_langs:
                return available_langs[0]
            return "NULL"
        else:
            # Language is a word instead of code, look for language and use that
            # code
            languages_match = [
                l for l in languages if language.lower() in l["english"].lower()]

            if len(languages_match) > 1:
                print(
                    "Found multiple matching languages, please choose the language you want to download from the following options.")

                for count, item in enumerate(languages_match, start=1):
                    print(f'{count}: {item["english"]}')

                try:
                    lang = int(
                        input(f'Choose a number matching the position of the language: '))
                except ValueError:
                    logging.warning(
                        'Language option selected is not a number, using NULL as language.')
                    print("That's not a number.")
                    return "NULL"

                if lang not in range(1, (len(languages_match) + 1)):
                    logging.warning(
                        'Language option selected is not in the accepted range.')
                    print('Not a valid language option.')
                    return "NULL"

                lang_to_use = languages_match[(lang - 1)]
                return lang_to_use["md"]

            return languages_match[0]["md"]

    def _get_chapter_number(self) -> Optional[str]:
        chapter_number = self._zip_name_match.group("chapter")
        if chapter_number is not None:
            parts = re.split(r'\.|\-', chapter_number)
            parts[0] = '0' if len(parts[0].lstrip(
                '0')) == 0 else parts[0].lstrip('0')

            chapter_number = '.'.join(parts)

        # Chapter is a oneshot
        if self._zip_name_match.group("prefix") is None:
            chapter_number = None
            logging.info(
                'No chapter number prefix found, uploading as oneshot.')

        return chapter_number

    def _get_volume_number(self) -> Optional[str]:
        volume_number = self._zip_name_match.group("volume")
        if volume_number is not None:
            volume_number = volume_number.lstrip('0')
            # Volume 0
            if len(volume_number) == 0:
                volume_number = '0'

        return volume_number

    def _get_chapter_title(self) -> Optional[str]:
        chapter_title = self._zip_name_match.group("chapter_title")
        if chapter_title is not None:
            # Add the question mark back to the chapter title
            chapter_title = chapter_title.replace('<question_mark>', '?')

        return chapter_title

    def _get_groups(self) -> List[Optional[UUID]]:
        groups = []
        groups_match = self._zip_name_match.group("group")
        if groups_match is not None:
            # Split the zip name groups into an array and remove any
            # leading/trailing whitespace
            groups_array = groups_match.split('+')
            groups_array = [g.strip() for g in groups_array]

            # Check if the groups are using uuids, if not, use the id map for
            # the id
            for group in groups_array:
                if not uuid_regex.match(group):
                    try:
                        group_id = self._names_to_ids["group"].get(group, None)
                    except KeyError:
                        logging.warning(
                            f'No group id found for {group}, not tagging the upload with this group.')
                        group_id = None
                    if group_id is not None:
                        groups.append(group_id)
                else:
                    groups.append(group)

        if not groups:
            logging.info('Zip groups array is empty, using group fallback.')
            print(f'No groups found, using group fallback.')
            groups = [] if self._config["User Set"]["group_fallback_id"] == '' else [
                self._config["User Set"]["group_fallback_id"]]
            if not groups:
                logging.info(
                    'Group fallback not found, uploading without a group.')
                print('Group fallback not found, uploading without a group.')

        return groups

    def process_zip_name(self) -> bool:
        self._zip_name_match = self._match_file_name()
        if self._zip_name_match is None:
            logging.error(
                f"No values processed from {self._to_upload}, skipping.")
            return False

        self.manga_series = self._get_manga_series()

        if self.manga_series is None:
            logging.error(
                f"Couldn't find a manga id for {self._zip_name}, skipping.")
            print(f'Skipped {self._zip_name}, no manga id found.')
            return False

        self.language = self._get_language()
        self.chapter_number = self._get_chapter_number()
        self.volume_number = self._get_volume_number()
        self.groups = self._get_groups()
        self.chapter_title = self._get_chapter_title()

        upload_details = f'Manga id: {self.manga_series}, chapter: {self.chapter_number}, volume: {self.volume_number}, title: {self.chapter_title}, language: {self.language}, groups: {self.groups}.'
        logging.info(f'Chapter upload details: {upload_details}')
        print(upload_details)
        return True


class ChapterUploaderProcess:

    def __init__(
            self,
            to_upload: Path,
            session: requests.Session,
            names_to_ids: dict,
            config: configparser.RawConfigParser,
            failed_uploads: list):
        self.to_upload = to_upload
        self.session = session
        self.names_to_ids = names_to_ids
        self.config = config
        self.failed_uploads = failed_uploads
        self.zip_name = to_upload.name
        self.zip_extension = to_upload.suffix

        self.uploaded_files_path = Path(self.config["Paths"]["uploaded_files"])
        self.images_upload_session = int(
            self.config["User Set"]["number_of_images_upload"])
        self.number_upload_retry = int(self.config["User Set"]["upload_retry"])
        self.ratelimit_time = ratelimit_time

        self.images_to_upload: List[List[Dict[str, bytes]]] = []
        self.images_to_upload_names: Dict[str, str] = {}
        self.images_to_upload_ids: List[UUID] = []

    def _get_images_to_upload(self):
        # Open zip file and read the data
        with zipfile.ZipFile(self.to_upload) as myzip:
            info_list = myzip.infolist()
            # Remove any directories and none-image files from the zip info
            # array
            info_list_images_only = [
                image.filename for image in info_list if (
                    not image.is_dir() and Path(
                        image.filename).suffix in (
                        '.png', '.jpg', '.jpeg', '.gif'))]
            logging.info(f'Images to upload: {info_list_images_only}')
            # Separate the image array into smaller arrays of 5 images
            info_list_separate = [info_list_images_only[l:l + self.images_upload_session]
                                  for l in range(0, len(info_list_images_only), self.images_upload_session)]

            for array_index, images in enumerate(info_list_separate, start=1):
                files = {}
                # Read the image data and add to files dict
                for image_index, image in enumerate(images, start=1):
                    image_filename = str(Path(image).name)
                    renamed_file = str(info_list_images_only.index(image))
                    self.images_to_upload_names.update(
                        {renamed_file: image_filename})
                    with myzip.open(image) as myfile:
                        files.update({renamed_file: myfile.read()})
                self.images_to_upload.append(files)

    def _upload_images(self, upload_session_id: UUID,
                       image_batch: Dict[str, bytes]) -> bool:
        image_retries = 0
        failed_image_upload = False
        while image_retries < self.number_upload_retry:
            # Upload the images
            image_upload_response = self.session.post(
                f'{md_upload_api_url}/{upload_session_id}', files=image_batch)
            if image_upload_response.status_code != 200:
                error = print_error(image_upload_response)
                logging.error(f"Error uploading images. Error: {error}")
                failed_image_upload = True
                image_retries += 1
                time.sleep(self.ratelimit_time)
                continue

            # Some images returned errors
            uploaded_image_data = convert_json(image_upload_response)
            succesful_upload_data = uploaded_image_data["data"]
            if uploaded_image_data["errors"] or uploaded_image_data["result"] == 'error':
                error = print_error(image_upload_response)
                logging.warning(f"Some images errored out. Error: {error}")

            # Add successful image uploads to the image ids array
            for uploaded_image in succesful_upload_data:
                uploaded_image_attributes = uploaded_image["attributes"]
                original_filename = uploaded_image_attributes["originalFileName"]
                file_size = uploaded_image_attributes["fileSize"]
                self.images_to_upload_ids.insert(
                    int(original_filename), uploaded_image["id"])
                succesful_upload_message = f'Success: Uploaded page {self.images_to_upload_names[original_filename]}, size: {file_size} bytes.'
                logging.info(succesful_upload_message)
                print(succesful_upload_message)

            if len(succesful_upload_data) == len(image_batch):
                logging.info('Uploaded all images in current batch.')
                failed_image_upload = False
                image_retries == self.number_upload_retry
                break
            else:
                image_batch = {k: v for (k, v) in image_batch.items() if k not in [
                    i["attributes"]["originalFileName"] for i in succesful_upload_data]}
                logging.warning(
                    f"Some images didn't upload, retrying. Failed images: {image_batch}")
                failed_image_upload = True
                image_retries += 1
                time.sleep(self.ratelimit_time)
                continue

        return failed_image_upload

    def _remove_upload_session(self, upload_session_id: UUID):
        """Delete the upload session."""
        self.session.delete(f'{md_upload_api_url}/{upload_session_id}')
        logging.info(f'Sent {upload_session_id} to be deleted.')

    def _delete_exising_upload_session(self):
        """Remove any exising upload sessions to not error out as mangadex only allows one upload session at a time."""
        removal_retry = 0
        while removal_retry < self.number_upload_retry:
            existing_session = self.session.get(f'{md_upload_api_url}')
            if existing_session.status_code == 200:
                existing_session_json = convert_json(existing_session)
                if existing_session_json is None:
                    removal_retry += 1
                    logging.warning(
                        f"Couldn't convert exising upload session response into a json, retrying.")
                else:
                    self._remove_upload_session(
                        existing_session_json["data"]["id"])
                    return
            elif existing_session.status_code == 404:
                logging.info("No existing upload session found.")
                return
            elif existing_session.status_code == 401:
                logging.warning("Not logged in, logging in and retrying.")
                login_to_md(self.session, config)
                removal_retry += 1
            else:
                removal_retry += 1
                logging.warning(
                    f"Couldn't delete the exising upload session, retrying.")

            time.sleep(self.ratelimit_time)

        logging.error("Exising upload session not deleted.")

    def _create_upload_session(self) -> Optional[dict]:
        """Try create an upload session 3 times."""
        chapter_upload_session_retry = 0
        chapter_upload_session_successful = False
        while chapter_upload_session_retry < self.number_upload_retry:
            self._delete_exising_upload_session()
            time.sleep(self.ratelimit_time)
            # Start the upload session
            upload_session_response = self.session.post(
                f'{md_upload_api_url}/begin',
                json={
                    "manga": self.processed_zip_object.manga_series,
                    "groups": self.processed_zip_object.groups})

            if upload_session_response.status_code == 401:
                login_to_md(self.session, config)

            elif upload_session_response.status_code != 200:
                error = print_error(upload_session_response)
                logging.error(
                    f"Couldn't create upload draft for {self.zip_name}. Error: {error}")
                print(f'Error creating draft for {self.zip_name}.')

            if upload_session_response.status_code == 200:
                upload_session_response_json = convert_json(
                    upload_session_response)

                if upload_session_response_json is not None:
                    chapter_upload_session_successful = True
                    chapter_upload_session_retry == self.number_upload_retry
                    return upload_session_response_json
                else:
                    upload_session_response_json_message = f"Couldn't convert successful upload session creation for {self.to_upload} into a json, retrying."
                    logging.error(upload_session_response_json_message)
                    print(upload_session_response_json_message)

            chapter_upload_session_retry += 1
            time.sleep(self.ratelimit_time)

        # Couldn't create an upload session, skip the chapter
        if not chapter_upload_session_successful:
            upload_session_response_json_message = f"Couldn't create an upload session for {self.to_upload}."
            logging.error(upload_session_response_json_message)
            print(upload_session_response_json_message)
            self.failed_uploads.append(self.to_upload)
            return

    def _commit_chapter(self, upload_session_id: UUID) -> bool:
        """Try commit the chapter to mangadex."""
        commit_retries = 0
        succesful_upload = False
        while commit_retries < self.number_upload_retry:
            chapter_commit_response = self.session.post(
                f'{md_upload_api_url}/{upload_session_id}/commit',
                json={
                    "chapterDraft": {
                        "volume": self.processed_zip_object.volume_number,
                        "chapter": self.processed_zip_object.chapter_number,
                        "title": self.processed_zip_object.chapter_title,
                        "translatedLanguage": self.processed_zip_object.language},
                    "pageOrder": self.images_to_upload_ids})

            if chapter_commit_response.status_code == 200:
                succesful_upload = True
                chapter_commit_response_json = convert_json(
                    chapter_commit_response)

                if chapter_commit_response_json is not None:
                    succesful_upload_id = chapter_commit_response_json["data"]["id"]
                    print(
                        f'Succesfully uploaded: {succesful_upload_id}, {self.zip_name}.')
                    logging.info(
                        f"Succesful commit: {succesful_upload_id}, {self.zip_name}.")

                    # Move the uploaded zips to a different folder
                    self.uploaded_files_path.mkdir(parents=True, exist_ok=True)
                    if f'{self.zip_name}{self.zip_extension}' in os.listdir(self.uploaded_files_path):
                        zip_name = f'{self.zip_name}{{2}}'
                        logging.warning(f'{self.zip_name} already exists in {self.uploaded_files_path}, renaming to {zip_name}.')
                    else:
                        zip_name = self.zip_name

                    new_uploaded_zip_path = self.to_upload.rename(
                        self.uploaded_files_path.joinpath(
                            zip_name).with_suffix(
                            self.zip_extension))
                    logging.info(
                        f'Moved {self.to_upload} to {new_uploaded_zip_path}.')
                    commit_retries == self.number_upload_retry
                    return True

                chapter_commit_response_json_message = f"Couldn't convert successful chapter commit api response into a json"
                logging.error(chapter_commit_response_json_message)
                print(chapter_commit_response_json_message)
                return True

            elif chapter_commit_response.status_code == 401:
                login_to_md(self.session, config)

            else:
                commit_fail_message = f'Failed to commit {self.zip_name}, error {chapter_commit_response.status_code} trying again.'
                logging.warning(commit_fail_message)
                print(commit_fail_message)

            commit_retries += 1
            time.sleep(self.ratelimit_time)

        if not succesful_upload:
            commit_error_message = f'Failed to commit {self.zip_name}, removing upload draft.'
            logging.error(commit_error_message)
            print(commit_error_message)
            self._remove_upload_session(upload_session_id)
            self.failed_uploads.append(self.to_upload)
            return False

    def start_chapter_upload(self):
        # Only accept zip files
        if self.zip_extension not in ('.zip', '.cbz'):
            logging.error(
                f"{self.to_upload} doesn't have the correct extension, skipping.")
            return

        self.processed_zip_object = FileProcesser(
            self.to_upload, self.names_to_ids, self.config)
        processed_zip = self.processed_zip_object.process_zip_name()
        if not processed_zip:
            return

        if 'Authorization' not in self.session.headers:
            login_to_md(self.session, config)

        upload_session_response_json = self._create_upload_session()
        if upload_session_response_json is None:
            time.sleep(self.ratelimit_time)
            return

        upload_session_id = upload_session_response_json["data"]["id"]
        upload_session_id_message = f'Created upload session: {upload_session_id}, {self.zip_name}.'
        logging.info(upload_session_id_message)
        print(upload_session_id_message)

        self._get_images_to_upload()

        failed_image_upload = False
        for array_index, image_batch in enumerate(
                self.images_to_upload, start=1):
            failed_image_upload = self._upload_images(
                upload_session_id, image_batch)

            if failed_image_upload:
                break

            # Rate limit
            if array_index % 5 == 0:
                logging.debug('Sleeping between image uploads.')
                time.sleep(self.ratelimit_time)

        # Skip chapter upload and delete upload session
        if failed_image_upload:
            failed_image_upload_message = f'Deleting draft due to failed image upload: {upload_session_id}, {self.zip_name}.'
            print(failed_image_upload_message)
            logging.error(failed_image_upload_message)
            self._remove_upload_session(self.session, upload_session_id)
            self.failed_uploads.append(self.to_upload)
            return

        logging.info("Uploaded all of the chapter's images.")
        self._commit_chapter(upload_session_id)

        logging.debug('Sleeping between zip upload.')
        time.sleep(self.ratelimit_time * 2)


def get_zips_to_upload(
        config: configparser.RawConfigParser) -> Optional[List[Path]]:
    to_upload_folder_path = Path(config["Paths"]["uploads_folder"])
    zips_to_upload = [
        x for x in to_upload_folder_path.iterdir() if x.suffix in (
            '.zip', '.cbz')]
    zips_to_not_upload = [
        x for x in to_upload_folder_path.iterdir() if x.suffix not in (
            '.zip', '.cbz')]

    if not zips_to_not_upload:
        logging.warning(f'Skipping files: {zips_to_not_upload}')

    if not zips_to_upload:
        no_zips_found_error_message = 'No zips found to upload, exiting.'
        print(no_zips_found_error_message)
        logging.error(no_zips_found_error_message)
        return

    logging.info(f'Uploading files: {zips_to_upload}')
    return zips_to_upload


def main(config: configparser.RawConfigParser):
    zips_to_upload = get_zips_to_upload(config)
    if zips_to_upload is None:
        return

    session = make_session()
    names_to_ids = open_manga_series_map(config, root_path)
    failed_uploads = []

    for index, to_upload in enumerate(zips_to_upload, start=1):
        ChapterUploaderProcess(
            to_upload,
            session,
            names_to_ids,
            config,
            failed_uploads).start_chapter_upload()

        if index % 3 == 0 and 'Authorization' in session.headers:
            session = make_session(
                {"Authorization": session.headers["Authorization"]})

    if failed_uploads:
        logging.info(f'Failed uploads: {failed_uploads}')
        print(f'Failed uploads:')
        for fail in failed_uploads:
            print(fail)


if __name__ == "__main__":

    main(config)
