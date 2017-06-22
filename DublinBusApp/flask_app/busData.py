from flask import jsonify
import csv

class BusDB:
    '''Class that deals with querying DB.'''

    def __init__(self):
        pass

    def route_info(self, route_num):
        stop_info = open('static/busstopinfo_bac_only.csv', 'r')
        reader = csv.reader(stop_info)
        stops = []

        headings = next(reader)
        for row in reader:

            routes = row[8].split(",")

            if route_num in routes:

                stop = {
                    'stop_id': row[0],
                    'display_stop_id': row[1],
                    'shortname': row[2],
                    'fullname': row[3],
                    'latitude': float(row[4]),
                    'longitude': float(row[5]),
                    'route': routes
                }
                stops.append(stop)

        # Returning info
        return jsonify({'stops': stops})