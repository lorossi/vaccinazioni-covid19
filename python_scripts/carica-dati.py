import os
import json
import logging
import requests
import subprocess
from pathlib import Path
from datetime import datetime, timedelta


def main():
    push_to_github = True
    # filenames
    json_filename = "vaccini.json"
    js_filename = "vaccini.js"
    js_history_filename = "storico_vaccini.js"
    # file paths
    output_path = "output/"
    assets_path = "../assets/"
    # italian population to calculate percentage
    italian_population = 60317000
    # initialize dictionaries
    data = {
        "territori": [],
        "categorie": [],
        "sesso": [],
        "fasce_eta": []
        }
    italia = {
        "nome_territorio": "Italia",
        "codice_territorio": None
    }
    # load timestamp that will be put inside the output
    now = datetime.now()
    data["script_timestamp"] = now.isoformat()
    data["last_updated"] = now.strftime("%Y-%m-%d ore %H:%M")
    # current working directory
    cwd = os.getcwd() + "/"

    logging.info("Loading settings")

    # load headers
    with open("settings/headers.json") as f:
        headers = json.load(f)

    # load payload and url
    with open("settings/payloads.json", "r") as f:
        payload = json.load(f)

    # load territories ISTAT code
    with open("settings/codici_regione.json", "r") as f:
        territories_codes = json.load(f)

    logging.info("Loading old data")
    last_data = None
    try:
        # try to load old data to make a comparision
        with open(output_path + json_filename, "r") as f:
            old_data = json.load(f)
            # sort old data so the newest one is the first
            old_data.sort(key=lambda x: datetime.fromisoformat(x['script_timestamp']), reverse=True)
            # get last midnight
            midnight = datetime.now().replace(hour=0, minute=0, second=0)
            # now start iterating until we find data from yesterday (if any)
            for x in range(len(old_data)):
                if midnight > datetime.fromisoformat(old_data[x]["script_timestamp"]):
                    # found the most recent data for the prior day
                    last_data = old_data[x]
                    break

    except Exception as e:
        # no old previuos file has been found
        logging.info("No previous record. Unable to calculate variation. "
                     f"Error: {e}")

    logging.info("Requesting data about terriories")
    response = requests.post(payload["url"], headers=headers, data=payload["totale_vaccini"]).text
    json_response = json.loads(response)

    logging.info("Scraping territories")
    # load data from the response
    data["last_data_update"] = json_response["results"][0]["result"]["data"]["timestamp"]
    # iterate over each territory
    for territory in json_response["results"][0]["result"]["data"]["dsr"]["DS"][0]["PH"][1]["DM1"]:
        # format territory name to later match the code
        territory_name = territory["C"][0].replace("P.A.", "").replace("-", " ").strip().upper()
        territory_code = None

        # look for ISTAT territory code
        for code in territories_codes:
            if territories_codes[code] == territory_name:
                territory_code = code
                break

        # init the dict with all the new data
        new_data = {
            "nome_territorio": territory["C"][0],
            "codice_territorio": territory_code,
            "totale_dosi_consegnate": territory["C"][3],
            "totale_vaccinati": territory["C"][1],
            "percentuale_popolazione_vaccinata": float(territory["C"][2]),
            "percentuale_dosi_utilizzate": territory["C"][1] / territory["C"][3] * 100
        }

        # find the data for yesterday
        last_territory = None
        if last_data is not None:
            for old_territory in last_data["territori"]:
                if old_territory["nome_territorio"] == new_data["nome_territorio"]:
                    last_territory = old_territory
                    break

        # if found, compare
        if last_territory is not None:
            new_data["nuove_dosi_consegnate"] = new_data["totale_dosi_consegnate"] - old_territory["totale_dosi_consegnate"]
            new_data["percentuale_nuove_dosi_consegnate"] = new_data["nuove_dosi_consegnate"] / old_territory["totale_dosi_consegnate"] * 100
            new_data["nuovi_vaccinati"] = new_data["totale_vaccinati"] - last_territory["totale_vaccinati"]
            new_data["percentuale_nuovi_vaccinati"] = new_data["nuovi_vaccinati"] / last_territory["totale_vaccinati"] * 100

        # finally append data to the dict
        data["territori"].append(new_data)

        # update total number of doses and vaccinated people
        if "totale_dosi_consegnate" not in italia:
            italia["totale_dosi_consegnate"] = territory["C"][3]
            italia["totale_vaccinati"] = territory["C"][1]
        else:
            italia["totale_dosi_consegnate"] += territory["C"][3]
            italia["totale_vaccinati"] += territory["C"][1]

    # calculate the percentage of vaccinated people
    italia["percentuale_popolazione_vaccinata"] = italia["totale_vaccinati"] / italian_population * 100
    italia["percentuale_dosi_utilizzate"] = italia["totale_vaccinati"] / italia["totale_dosi_consegnate"] * 100

    # now load categories
    logging.info("Requesting data about categories")
    response = requests.post(payload["url"], headers=headers, data=payload["categorie"]).text
    json_response = json.loads(response)

    for category in json_response["results"][0]["result"]["data"]["dsr"]["DS"][0]["PH"][0]["DM0"]:
        category_id = int(category["C"][0][0])
        category_name = category["C"][0][4:]
        total_number = category["C"][1]

        # init the dict with all the new data
        new_data = {
            "id_categoria": category_id,
            "nome_categoria": category_name,
            "totale_vaccinati": total_number,
        }

        # iterate over last data to find the variation
        if last_data is not None:
            for category in last_data["categorie"]:
                if category["nome_categoria"] == category_name:
                    if "totale_vaccinati" in category:
                        # add variation from yesterday
                        variation = total_number - category["totale_vaccinati"]
                        new_data["nuovi_vaccinati"] = variation
                        new_data["percentuale_nuovi_vaccinati"] = variation / total_number * 100
                        break

        # finally append data to the dict
        data["categorie"].append(new_data)

    # now load women
    logging.info("Requesting data about women")
    response = requests.post(payload["url"], headers=headers, data=payload["donne"]).text
    json_response = json.loads(response)

    women = json_response["results"][0]["result"]["data"]["dsr"]["DS"][0]["PH"][0]["DM0"][0]["M0"]

    new_dict = {
        "nome_categoria": "donne",
        "totale_vaccinati": women
    }

    if last_data is not None:
        for gender in last_data["sesso"]:
            if gender["nome_categoria"] == "donne":
                if "totale_vaccinati" in gender:
                    # calculate variation
                    variation = women - gender["totale_vaccinati"]
                    new_dict["nuovi_vaccinati"] = variation
                    new_dict["percentuale_nuovi_vaccinati"] = variation / women * 100

    # finally append to data
    data["sesso"].append(new_dict)

    # now load men
    logging.info("Requesting data about men")
    response = requests.post(payload["url"], headers=headers, data=payload["uomini"]).text
    json_response = json.loads(response)

    men = json_response["results"][0]["result"]["data"]["dsr"]["DS"][0]["PH"][0]["DM0"][0]["M0"]
    new_dict = {
        "nome_categoria": "uomini",
        "totale_vaccinati": men
    }

    if last_data is not None:
        for gender in last_data["sesso"]:
            if gender["nome_categoria"] == "uomini":
                if "totale_vaccinati" in gender:
                    # calculate variation
                    variation = men - gender["totale_vaccinati"]
                    new_dict["nuovi_vaccinati"] = variation
                    new_dict["percentuale_nuovi_vaccinati"] = variation / men * 100

    # finally append to data
    data["sesso"].append(new_dict)

    # now load age ranges
    logging.info("Requesting data about age rages")
    response = requests.post(payload["url"], headers=headers, data=payload["eta"]).text
    json_response = json.loads(response)

    for age_range in json_response["results"][0]["result"]["data"]["dsr"]["DS"][0]["PH"][0]["DM0"]:
        category_name = age_range["C"][0]
        total_number = age_range["C"][1]

        # init the dict with all the new data
        new_data = {
            "nome_categoria": category_name,
            "totale_vaccinati": total_number,
        }

        # iterate over last data to find the variation
        if last_data is not None:
            for age in last_data["fasce_eta"]:
                if age["nome_categoria"] == category_name:
                    if "totale_vaccinati" in age:
                        variation = total_number - age["totale_vaccinati"]
                        new_data["nuovi_vaccinati"] = variation
                        new_data["percentuale_nuovi_vaccinati"] = variation / total_number * 100
                        break

        # finally append data to the dict
        data["fasce_eta"].append(new_data)

    # now look for old data about italy as whole
    last_italy = None
    if last_data is not None:
        for territory in last_data["territori"]:
            if territory["nome_territorio"] == "Italia":
                last_italy = territory

    # if found, update the variation
    if last_italy is not None:
        italia["nuove_dosi_consegnate"] = italia["totale_dosi_consegnate"] - last_italy["totale_dosi_consegnate"]
        italia["nuovi_vaccinati"] = italia["totale_vaccinati"] - last_italy["totale_vaccinati"]

    # finally, append to dict the data about italy
    data["territori"].append(italia)
    logging.info("Data scraped")

    # create output folders
    # important for github automation
    logging.info("Creating folders")
    Path(output_path).mkdir(parents=True, exist_ok=True)
    Path(assets_path).mkdir(parents=True, exist_ok=True)

    logging.info("Saving to file")
    try:
        # load old data to update the file
        with open(output_path + json_filename, "r") as f:
            old_data = json.load(f)
            # sort by time so new data is always on top
            old_data.sort(key=lambda x: datetime.fromisoformat(x['script_timestamp']), reverse=True)
    except Exception as e:
        logging.error(f"Error while opening dest file. Error: {e}")
        logging.error("Creating new file.")
        # no old data has been found.
        # the new data must be encapsulated in a list before dumping it into
        # a json file
        old_data = [data]

    # loop trhought old data in order to update the dictionary
    found = False
    current_timestamp = datetime.fromisoformat(data["script_timestamp"])
    for d in old_data:
        old_timestamp = datetime.fromisoformat(d["script_timestamp"])
        if  current_timestamp.date() == old_timestamp.date():
            # update dictionary
            found = True
            d |= data
            # log info
            logging.info("Data for today already found with timestamp: "
                         f"{old_timestamp}")
            break

    if not found:
        old_data.append(data)
        logging.info("No old data found for today. Appending.")

    print(data["script_timestamp"])

    # now finally save the json file
    with open(output_path + json_filename, "w") as f:
        json.dump(old_data, f, indent=2)

    logging.info(f"Json file saved. Path: {cwd}{json_filename}")


    # save the js file for the website
    # luckily, js objects and json have the same structure
    with open(assets_path + js_filename, "w") as f:
        js_string = "let vaccini = "
        # convert dict to json (will be read by js)
        js_string += json.dumps(data, indent=2)
        js_string += ";"
        f.write(js_string)
    logging.info(f"JS file saved. Path: {cwd}{js_filename}")


    # create a js file with all the data about vaccines
    # midnight for the considered day
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # last midnight from now
    last_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    history = []
    for d in old_data:
        new_data = {}
        timestamp = d["script_timestamp"]
        time_obj = datetime.fromisoformat(timestamp)
        # the data we are looking for is older than last midnght and closest to midnight (rolling)
        if (midnight - time_obj).total_seconds() >= 0 and (last_midnight - time_obj).total_seconds() >= 0:
            new_timestamp = datetime.fromisoformat(timestamp).strftime("%Y-%m-%d")
            new_data["script_timestamp"] = new_timestamp
            new_data["territori"] = []

            for territory in d["territori"]:
                new_territory = {
                    "nome_territorio": territory["nome_territorio"],
                    "codice_territorio": territory.get("codice_territorio", None),
                    "totale_vaccinati": territory["totale_vaccinati"],
                    "totale_dosi_consegnate": territory["totale_dosi_consegnate"],
                    "percentuale_popolazione_vaccinata": float(territory["percentuale_popolazione_vaccinata"])
                }

                # legacy update - old data has not these keys
                if "percentuale_dosi_utilizzate" in territory:
                    new_territory["percentuale_dosi_utilizzate"] = territory["percentuale_dosi_utilizzate"]
                else:
                    new_territory["percentuale_dosi_utilizzate"] = territory["totale_vaccinati"] / territory["totale_dosi_consegnate"] * 100

                if "nuovi_vaccinati" in territory:
                    new_territory["nuovi_vaccinati"] = territory["nuovi_vaccinati"]
                else:
                    new_territory["nuovi_vaccinati"] = 0

                new_data["territori"].append(new_territory)
            history.append(new_data)
            midnight = time_obj.replace(hour=0, minute=0, second=0, microsecond=0)
    # reverse so the oldest one ore always on top
    history.reverse()

    # save the js file for the website
    # luckily, js objects and json have the same structure
    with open(assets_path + js_history_filename, "w") as f:
        js_string = "let storico_vaccini = "
        # convert dict to json (will be read by js)
        js_string += json.dumps(history, indent=2)
        js_string += ";"
        f.write(js_string)
    logging.info(f"JS history file saved. Path: {cwd}{js_history_filename}")

    if push_to_github:
        # now push all to to github
        logging.info("Pushing to GitHub")
        subprocess.run("git pull".split(" "))
        subprocess.run(["git", "add", cwd + output_path + json_filename])
        subprocess.run(["git", "add", cwd + assets_path + js_filename])
        subprocess.run(["git", "add", cwd + assets_path + js_history_filename])
        subprocess.run(["git", "pull"])
        subprocess.run(["git", "commit", "-m", "updated data"])
        subprocess.run(["git", "push"])
        logging.info("Pushed to GitHub")


if __name__ == "__main__":
    logfile = "logging.log"
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                        level=logging.INFO, filename=logfile,
                        filemode="a")
    print(f"Logging in {logfile}")

    logging.info("Script started")
    main()
    logging.info("Script ended")
