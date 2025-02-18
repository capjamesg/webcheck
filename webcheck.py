import json
import os
import re
import string
from datetime import datetime
from urllib.parse import urlparse
from collections import defaultdict

import requests
from bs4 import BeautifulSoup


def transform_name_into_id(name):
    # lowercase, remove all symbols
    return (
        name.lower()
        .translate(str.maketrans("", "", string.punctuation))
        .replace(" ", "-")
    )


operators = {
    "contains": lambda x, y: x in y.get_text().lower(),
    "not_contains": lambda x, y: x not in y.get_text().lower(),
    # this accepts a CSS selector
    "matches": lambda query, tree: bool(tree.select(query)),
}


class WebCheck:
    def __init__(self, checks, store_name="default.json"):
        self.checks = checks
        self.store_name = store_name

        if not os.path.exists(self.store_name):
            with open(self.store_name, "w") as f:
                f.write(json.dumps([]))

        with open(self.store_name, "r") as f:
            data = json.load(f)

        self.data = data


    def run(self, checks=[]):
        results = []

        if not checks:
            checks = self.checks

        for check in checks:
            task_responses = defaultdict(list)

            try:
                page_text = requests.get(check["url"]).text.lower()
            except Exception as e:
                results.append(
                    {
                        "check": check["id"],
                        "match": False,
                        "error": True,
                        "error_message": str(e),
                        "completed": datetime.now().isoformat(),
                    }
                )
                continue

            soup = BeautifulSoup(page_text, "html.parser")

            if check.get("scope", ""):
                soup = soup.select(check["scope"])
                if not soup:
                    results.append(
                        {
                            "check": check["id"],
                            "match": False,
                            "error": True,
                            "error_message": "Scope not found",
                            "completed": datetime.now().isoformat(),
                        }
                    )
                    continue
                soup = soup[0]

            if check["query_type"] == "plain_text":
                result = operators[check["operator"]](check["value"], soup)

                if check["tasks"]:
                    for task in check["tasks"]:
                        if task == "store_associated_text":
                            task_results = [
                                item.text
                                for item in soup.find_all(
                                    string=re.compile(check["value"])
                                )
                            ]
                            if task_results and all(task_results):
                                task_responses["store_associated_text"].extend(task_results)
                        elif task == "store_associated_link":
                            # get parent that contains link of interest

                            for item in soup.find_all(string=re.compile(check["value"])):
                                item = item.parent

                                link = None
                                parent = None

                                while link is None:
                                    parent = (
                                        parent
                                        or item.find(string=re.compile(check["value"]))
                                        and item.find(
                                            string=re.compile(check["value"])
                                        ).parent
                                    )
                                    if not parent:
                                        break
                                    link = parent.find("a")
                                    if link is not None:
                                        href = link[
                                            "href"
                                        ]
                                        parsed_href_netloc = urlparse(href).netloc
                                        if not parsed_href_netloc or (parsed_href_netloc.replace("www.", "") != urlparse(check["url"]).netloc.replace("www.", "")):
                                            href = (
                                                urlparse(check["url"]).scheme
                                                + "://"
                                                + urlparse(check["url"]).netloc
                                                + href
                                            )
                                        task_responses["store_associated_link"].append({"href":href, "text": link.get_text()})

                                        break
                                    parent = parent.parent
                                    if parent is None:
                                        break

                result = operators[check["operator"]](check["value"], soup)

            final_result = {
                "check": check["id"],
                "match": result,
                "error": False,
                "completed": datetime.now().isoformat(),
            }

            # dedupe task_responses["store_associated_link"] on href
            if task_responses.get("store_associated_link", ""):
                deduped = []
                seen = set()
                for item in task_responses["store_associated_link"]:
                    if item["href"] not in seen and item["text"]:
                        deduped.append(item)
                        seen.add(item["href"])
                task_responses["store_associated_link"] = deduped

            if task_responses:
                final_result["task_responses"] = task_responses

            results.append(final_result)

        self.data.extend(results)

    def save(self):
        with open(self.store_name, "w") as f:
            f.write(json.dumps(self.data, indent=4))

    def get_matches_for_task(self, task_name):
        return [item for item in self.data if item.get("check", "") == task_name]
