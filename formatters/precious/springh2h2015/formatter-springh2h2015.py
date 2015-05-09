#!/usr/bin/env python

from collections import defaultdict
import csv
import os
import logging
from pprint import pprint, pformat
import re
import subprocess
import sys


class App:
    def __init__(self, script_dir):
        self.params = {}
        self.script_dir = script_dir

    def get_results_filepath(self):
        results_dir = self.params.get("results_filepath", self.script_dir)
        return os.path.join(results_dir, self.params["results_leafname"])

    def get_template_filepath(self):
        results_dir = self.params.get("template_filepath", self.script_dir)
        return os.path.join(results_dir, self.params["template_leafname"])

    def get_mapping_filepath(self):
        results_dir = self.params.get("mapping_filepath", self.script_dir)
        return os.path.join(results_dir, self.params["mapping_leafname"])

    def get_capture_filepath(self, leafpath):
        results_dir = self.params["primary_dir"]
        return os.path.normpath(os.path.join(results_dir, leafpath))

    def get_primary_filepath(self, leafpath):
        results_dir = self.params["primary_dir"]
        return os.path.normpath(os.path.join(results_dir, leafpath))

    def convert_time(self, value):
        match = re.match(r"([0-5][0-9]):([0-5][0-9]):([0-5][0-9])", value)
        if not match:
            raise Exception("Cannot convert time %s" % value)
        return 3600.0 * int(match.group(1)) + 60 * int(match.group(2)) + int(match.group(3))

    def parse_csv(self):
        self.entries = {}
        self.categories = defaultdict(dict)
        with open(self.get_results_filepath(), 'rb') as csvfile:
            dialect = csv.Sniffer().sniff(csvfile.read(1024), ',')
            csvfile.seek(0)
            fieldnames = (
                "number",
                "clubname",
                "crewname",
                "boattype",
                "gender",
                "affiliation",
                "status",
                "category",
                "leg1time",
                "leg2time",
                "totaltime",
                "adjustedtime",
            )

            csvreader = csv.DictReader(csvfile, dialect=dialect, fieldnames=fieldnames)

            for item in csvreader:               
                if item["totaltime"].strip() in ("DNF", "DNR", "DNS"):
                    logging.warning("Skipping untimed crew %s" % pformat(item))
                else:
                    item['number'] = int(item['number'], 10)
                    number = item['number']
                    if number in self.entries:
                        raise Exception("Duplicate crew number %s" % number)

                    for key in ("leg1time", "leg2time", "totaltime"):
                        if item[key] != "":
                            item[key] = self.convert_time(item[key])
                            
                    if item['leg1time'] + item['leg2time'] != item['totaltime']:
                        raise Exception("Bad time for crew %d" % number)
                    self.entries[number] = item

                    self.categories[item["category"]][number] = item
                        
                    order_by = item["number"]

                    item["order_by"] = order_by
                    
        logging.info("Categories: %s" % (", ".join(sorted(self.categories.keys()))))
        self.category_order = {}
        self.category_fastest = {}
        
        for category, items in self.categories.iteritems():

            sorted_category = sorted(items.keys(), key = lambda x: self.entries[x]["totaltime"])

            self.category_order[category] = sorted_category
            self.category_fastest[category] = self.entries[sorted_category[0]]["totaltime"]



        for number, item in self.entries.iteritems():
            category = self.category_order[item["category"]]
            item["position"] = 1 + category.index(int(item["number"]))

            item["num_entries"] = len(category)
            item["fractional_time"] = item["totaltime"] / self.category_fastest[item["category"]]
            if item["fractional_time"] < 1.0 or item["fractional_time"] > 2.0:
                raise Exception("Bad fractional time %f" % item["fractional_time"])
                
            pass

        for key, order in self.category_order.iteritems():
            for index in range(0, len(order) - 1):
                entry1 = self.entries[order[index]]
                entry2 = self.entries[order[index+1]]

                if entry1["totaltime"] > entry2["totaltime"]:
                    raise Exception("Category sorting fault %s > %s (order %s)" %
                        (pformat(entry1), pformat(entry2), ", ".join([str(x) for x in order])))
        pass


    def generate_template(self):
        content = ""
        sorter = lambda x, y: cmp(self.entries[x]["order_by"], self.entries[y]["order_by"])
        for number in sorted(self.entries.keys(), cmp=sorter):
            item = self.entries[number]
            title = '%(number)s|%(clubname)s|%(crewname)s|%(category)s|%(leg1time)s|%(leg2time)s|%(totaltime)s|%(position)s|%(num_entries)s|%(fractional_time).6f' % item
            template = "Comp "

            content += "%s = %s\r\n" % (template, title)

        return content


    def get_dest_filename(self, number):
        item = self.entries[number]
        name = item["name"]
        name = re.sub(r"[^0-9A-Za-z +']", " ", name)
        filename = "%d %s %s %s, %d of %d.mp4" % (number, name, item["class"], item["type"], item["position"], item["num_entries"])
        return filename

    def generate_primary(self):
        self.mappings = []
        with open(self.get_mapping_filepath(), 'rb') as mappingfile:
            for line in mappingfile:
                if not line.startswith("#"):
                    match = re.match(r'([0-9A-Za-z./_ ]+) = (\d+)\|([^|]+)\|([^|]*)\|([^|]+)\|', line)
                    if not match:
                        logging.error("Undecodable mapping %s" % line)
                    else:
                        filepath = self.get_capture_filepath(match.group(1) + ".mp4")
                        if not os.path.exists(filepath):
                            logging.error("Missing file in mapping %s" % filepath)
                        else:
                            if match.group(4):
                                dest_filename = "%s %s %s (%s)" % match.group(2, 3, 4, 5) + ".mp4"
                            else:
                                dest_filename = "%s %s (%s)" % match.group(2, 3, 5) + ".mp4"
                            self.mappings += [{
                                "filepath": filepath,
                                "dest_filename": dest_filename
                            }]

        for mapping in self.mappings:
            dest_filepath = self.get_primary_filepath(mapping["dest_filename"])
            print "%s -> %s" % (mapping["filepath"], dest_filepath)
            if not os.path.isfile(dest_filepath):
                os.rename(mapping["filepath"], dest_filepath)
                pass
        
            
    def execute(self):
        self.parse_csv()
        with open(self.get_template_filepath(), 'wb') as template_file:
            template_file.write(self.generate_template())
        if not os.path.exists(self.get_mapping_filepath()):
            logging.info("Not generating primary footage because mapping file missing (%s)" % self.get_mapping_filepath())
        else:
            self.generate_primary()

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    script_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
    app = App(script_dir)
    division = "div4"
    app.params = {
        "results_leafname": "springh2h2015-results.csv",
        "template_leafname": "template-springh2h2015-results-%s.txt" % division,
        "mapping_leafname": "mapping-springh2h2015-results-%s.txt" % division,
        "capture_dir": os.path.normpath(os.path.join(script_dir, "../../../capture/precious/springh2h2015")),
        "primary_dir": os.path.normpath(os.path.join(script_dir, "../../../primary/derived/springh2h2015/%s" % division)),


    }
    if False:
        app.params.update({
            "mapping_leafname": "extras-hoc2013.txt",
            "primary_dir": os.path.normpath(os.path.join(script_dir, "../../../primary/derived/hoc2014/extras")),
        })

    app.execute()

    print "Done."
