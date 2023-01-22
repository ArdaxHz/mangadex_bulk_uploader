import logging
from io import BytesIO
from threading import Timer
from zipfile import ZipFile

import requests
from packaging import version

from uploader import __version__
from uploader.utils.config import root_path

logger = logging.getLogger("md_uploader")


def raise_error(ex):
    raise ex


def check_for_update():
    """Check For any program updates."""
    logger.debug("Looking for program update.")

    update = False
    local_version = version.parse(__version__)
    remote_release = requests.get(
        "https://api.github.com/repos/ArdaxHz/mangadex_bulk_uploader/releases/latest"
    )
    if remote_release.ok:
        remote_release_json = remote_release.json()
        remote_version = version.parse(remote_release_json["tag_name"])

        if remote_version > local_version:
            print(f"Update found: (old){local_version} (new){remote_version}.")
            logger.info(f"Update found: (old){local_version} (new){remote_version}.")
            if remote_version.major != local_version.major:
                print(
                    f"""The new version may have breaking changes, please check the github releases page for a list of changes
                    https://github.com/ArdaxHz/mangadex_bulk_uploader/releases/latest"""
                )

            timeout = 5
            t = Timer(timeout, raise_error, [ValueError("Not updating.")])
            t.start()
            answer = input("Do you want to update? 'y' or 'n'")
            t.cancel()

            if answer.lower() in ["true", "1", "t", "y", "yes"]:
                update = True
            else:
                update = False

            if not update:
                print(f"Not updating.")
                logger.info(f"Skipping update {remote_version}")
                return

            zip_resp = requests.get(remote_release_json["zipball_url"])
            if zip_resp.ok:
                myzip = ZipFile(BytesIO(zip_resp.content))
                zip_root = [z for z in myzip.infolist() if z.is_dir()][0].filename
                zip_files = [z for z in myzip.infolist() if not z.is_dir()]

                for fileinfo in zip_files:
                    filename = root_path.joinpath(
                        fileinfo.filename.replace(zip_root, "")
                    )
                    filename.parent.mkdir(parents=True, exist_ok=True)
                    file_data = myzip.read(fileinfo)

                    with open(filename, "wb") as fopen:
                        fopen.write(file_data)

                print(f"Updated, restart the ")
                logger.info(f"Updated to version {remote_version}")
                return

    logger.info(f"Updating error.")
    print(f"Couldn't update.")
