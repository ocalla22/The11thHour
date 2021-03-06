# http://flask.pocoo.org/
from flask import Flask, render_template, request, g, flash, redirect, url_for, session, Markup

# https://flask-cors.readthedocs.io/en/latest/
from flask_cors import CORS

from busData import api, dbi, everything

# https://docs.python.org/3/library/datetime.html
from _datetime import datetime

# https://www.sqlalchemy.org/
from sqlalchemy import create_engine

# https://wtforms.readthedocs.io/en/latest/
from wtforms import Form, StringField, PasswordField, validators

# https://passlib.readthedocs.io/en/stable/
from passlib.hash import sha256_crypt

# https://docs.python.org/3/library/functools.html
from functools import wraps

# http://pymysql.readthedocs.io/en/latest/index.html
import pymysql
pymysql.install_as_MySQLdb()

import json

# --------------------------------------------------------------------------#
# Creating Flask App
app = Flask(__name__)
# Enable Cross Origin Resource Sharing
CORS(app)

# --------------------------------------------------------------------------#

# Class for form
class RegisterForm(Form):
    name = StringField('Name', [validators.length(min=1, max=50)])
    username = StringField('Username', [validators.length(min=4, max=25)])
    email = StringField('Email', [validators.length(min=4, max=50)])
    work = StringField('Work Address(optional)')
    home = StringField('Home Address(optional)')
    password = PasswordField('Password', [
        validators.DataRequired(),
        validators.EqualTo('confirm', message='Passwords do not match')
    ])
    confirm = PasswordField('Confirm Password')


# --------------------------------------------------------------------------#
# Index Page
@app.route('/', methods=['GET', 'POST'])
def index():

    if request.method == 'POST':

        # If the user select the normal GO button do this
        if request.form['submit'] == 'normal':
            # Gets the user input from the destination input textbox
            dest = request.form['destination']
            # Check if the user has said to use geolocation. If they do use it. If not use the source input.
            use_geolocation = request.form.getlist('user_location')
            if use_geolocation == ["on"]:
                src_lat = request.form['users_lat_text']
                src_long = request.form['users_long_text']
                src = (float(src_lat), float(src_long))
            else:
                src = request.form['origin']
                src_lat, src_long = dbi().location_from_address(src)
                src = (src_lat, src_long)
        # If the user is logged in and requests Get me to Work
        elif request.form['submit'] == 'work':
            # Get the address from the DB
            username = session['username']
            engine = get_db()
            sql_work = "SELECT work FROM users WHERE username = %s"
            result_work = engine.execute(sql_work, [username])
            data_work = result_work.fetchall()
            dest = data_work[0][0]
            # Get the geolocation. If it has not loaded yet give error.
            try:
                src_lat = request.form['users_lat_text']
                src_long = request.form['users_long_text']
                src = (float(src_lat), float(src_long))
            except ValueError as ex:
                error_html = "Error. Geolocation not found. Please wait and try again."
                return render_template('home.html', **locals())
        # If the user is logged in and requests Get me to Home
        elif request.form['submit'] == 'home':
            # Get the address from the DB
            username = session['username']
            engine = get_db()
            sql_home = "SELECT home FROM users WHERE username = %s"
            result_home = engine.execute(sql_home, [username])
            data_home = result_home.fetchall()
            dest = data_home[0][0]
            # Get the geolocation. If it has not loaded yet give error.
            try:
                src_lat = request.form['users_lat_text']
                src_long = request.form['users_long_text']
                src = (float(src_lat), float(src_long))
            except ValueError as ex:
                error_html = "Error. Geolocation not found. Please wait and try again."
                return render_template('home.html', **locals())

        # Get the destination lat and long
        dest_lat, dest_long = dbi().location_from_address(dest)
        dest = (dest_lat, dest_long)

        # Check if the user wants to depart now or in the future.
        now_arrive_depart_selection = request.form['now_arrive_depart']
        # If now, use current time
        if now_arrive_depart_selection == '0':
            time = datetime.now()
            date = time.date()
            weekday = time.weekday()
            hour = time.hour
            min = time.minute
        # If in the future get the time from the input boxes.
        else:
            # Try except to ensure the date & time inputs are correct.
            try:
                time = request.form['time'].split(":")
                date = request.form['date'].split(" ")
                year = int(date[2])
                dates = {'January,':1, 'February,':2, 'March,':3, 'April,':4, 'May,':5, 'June,':6, 'July,':7, 'August,':8, 'September,':9, 'October,':10, 'November,':11, 'December,':12 }
                month = dates[date[1]]
                day = int(date[0])
                weekday = datetime(year, month, day).weekday()
                hour = int(time[0])
                min = int(time[1])
                time = datetime(year, month, day, hour, min)
            except IndexError as ex:
                template = "An exception of type {0} occurred. Arguments:\n{1!r}"
                message = template.format(type(ex).__name__, ex.args)
                print(message)
                error_html = "Error! Date input incorrect."
                return render_template('home.html', **locals())

        # Try running the model. If index error occurs it means there are no route options.
        try:
            route_options, dart_lat_long_list = everything(src, dest, time)

        except IndexError as ex:
            error_html = "No valid routes found. Please try a more detailed or different address."
            return render_template('home.html', **locals())

        return render_template('route_options.html', **locals())

    return render_template('home.html', **locals())


# --------------------------------------------------------------------------#
# Search for Route Page
@app.route('/route_search', methods=['GET', 'POST'])
def route_search():
    """Takes the input from the user for route number and direction"""

    if request.method == 'POST':
        # Get the user input
        users_route = request.form['user_route']

        route_list = api().stop_and_route_lists()[0]
        # If user select an invalid route give an error.
        if users_route not in route_list:
            error_html = 'Error. ' + users_route + ' is an invalid route. Please select a valid route from the dropdown list.'
            return render_template('route_search.html', **locals())

        # Get the direction input.
        if request.form.get('direction') == 'on':
            direction = 0
        else:
            direction = 1

        if direction == 1:
            html = "Route " + users_route + " Stops Northbound"
        elif direction == 0:
            html = "Route " + users_route + " Stops Southbound"

    return render_template('route_search.html', **locals())


# --------------------------------------------------------------------------#
# Search for Stop Page
@app.route('/stop_search', methods=['GET', 'POST'])
def stop_search():
    """Initially this loads the stop_search page. If there is a POST request i.e. the user inputs something
    it will open the stop page of the requested stop"""

    if request.method == 'POST':
        stop_num = request.form['user_stop']
        # Error check to ensure input is a number.
        try:
            int(stop_num)
        except ValueError as ex:
            error_html = "Stop ID must be a number."
            return render_template('stop_search.html', **locals())

        stop_list = api().stop_and_route_lists()[1]
        if int(stop_num) not in stop_list:
            error_html = 'Error. ' + stop_num + ' is an invalid stop. Please select a valid stop ID from the dropdown list.'
            return render_template('stop_search.html', **locals())

        return render_template('bus_stop.html', **locals())

    return render_template('stop_search.html', **locals())


# --------------------------------------------------------------------------#
# Stop Info Page
@app.route('/stop/<string:stopnum>', methods=['GET', 'POST'])
def stop_info(stopnum):
    """Displays the stop info page. It is activated from the links on the route_search page."""
    stop_num = stopnum

    return render_template('bus_stop.html', **locals())


# --------------------------------------------------------------------------#
# User Registration Page
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm(request.form)
    #get the information from the form
    if request.method == 'POST' and form.validate():
        name = form.name.data
        email = form.email.data
        username = form.username.data
        work = form.work.data
        home = form.home.data
        password = sha256_crypt.encrypt(str(form.password.data))

        engine = get_db()
        #insert the info into table
        sql = "INSERT INTO users(name, email, username, home, work, password) VALUES(%s, %s, %s, %s, %s, %s)"
        engine.execute(sql, (name, email, username, work, home, password))
        flash('You are successfully registered, now you can log in', 'success')

    return render_template('register.html', form=form)


# --------------------------------------------------------------------------#
# User login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Get Form Fields
        username = request.form['username']
        password_candidate = request.form['password']

        engine = get_db()
        sql = "SELECT * FROM users WHERE username = %s"
        result = engine.execute(sql, [username])
        all_data = result.fetchall()

        if len(all_data) > 0:
            # Get stored hash
            data = all_data[0]
            password = data['password']

            # Compare passwords
            if sha256_crypt.verify(password_candidate, password):
                # Passed
                session['logged_in'] = True
                session['username'] = username
                flash('Your are now logged in', 'success')
                return redirect(url_for('myroutes'))
            else:
                error = 'Invalid login'
                return render_template('home.html', error=error)
        else:
            error = 'Username not found'
            return render_template('home.html', error=error)
    return render_template('login.html')


# --------------------------------------------------------------------------#
# Check if user logged in
def is_logged_in(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash('Unauthorized, Please login', 'danger')
            return redirect(url_for('login'))

    return wrap


# --------------------------------------------------------------------------#
# Dashboard
@app.route('/myroutes', methods=['GET', 'POST'])
@is_logged_in
def myroutes():
    # get home, work, like_stop from database
    username = session['username']
    engine = get_db()
    sql = "SELECT * FROM like_stop WHERE username = % s"
    result = engine.execute(sql, [username])
    all_data = result.fetchall()
    sql_home = "SELECT home FROM users WHERE username = % s"
    result_home = engine.execute(sql_home, [username])
    data_home = result_home.fetchall()
    sql_work = "SELECT work FROM users WHERE username = % s"
    result_work = engine.execute(sql_work, [username])
    data_work = result_work.fetchall()
    work = data_work[0][0]
    home = data_home[0][0]

    stopnamelist = [0] * len(all_data)
    stopidlist = [0] * len(all_data)
    for a in range(0, len(all_data)):
        stopidlist[a] = all_data[a][1]
    Length = len(all_data)
    for a in range(0, len(all_data)):
        sql = "SELECT Stop_name FROM Stops WHERE Stop_ID = % s"
        stopnamelist[a] = engine.execute(sql, [all_data[a]['stop_id']]).fetchall()[0][0]
    #change the home and work address
    if request.method == 'POST':
        if request.form['submit'] == 'work':
            new_work = request.form['work']
            sql_update ="UPDATE users SET work = % s WHERE username = % s"
            result = engine.execute(sql_update, [new_work, username])
            return redirect(url_for('myroutes'))
        elif request.form['submit'] == 'home':
            new_home = request.form['home']
            sql_update ="UPDATE users SET home = % s WHERE username = % s"
            result = engine.execute(sql_update, [new_home, username])
            return redirect(url_for('myroutes'))
    return render_template('myroutes.html', ** locals())


# --------------------------------------------------------------------------#
# delete the stop
@app.route('/delete', methods=['POST'])
@is_logged_in
def delete():
    if request.method == 'POST':
        username = session['username']
        stop_id = request.form['user_delete']

        engine = get_db()
        #delete the stop in database
        sql = "DELETE FROM like_stop WHERE username = %s AND stop_id = %s"
        result = engine.execute(sql, [username, stop_id])

        return redirect(url_for('myroutes'))

    return redirect(url_for('myroutes'))


# --------------------------------------------------------------------------#
# Logout
@app.route('/logout')
def logout():
    session.clear()
    flash('You are now logged out', 'success')
    return redirect(url_for('index'))


# --------------------------------------------------------------------------#
# user like function
@app.route('/likestop', methods=['POST'])
@is_logged_in
def likestop():
    if request.method == 'POST':
        stop_id = request.form['stopnum']

        username = session['username']

        engine = get_db()

        sql = "SELECT * FROM like_stop WHERE username = %s AND stop_id = %s"
        result = engine.execute(sql, [username, stop_id])
        all_data = result.fetchall()

        if len(all_data) > 0:
            flash('You have already added the stop into Myroutes', 'danger')
        else:
            sql = "INSERT INTO like_stop(username, stop_id) VALUES( %s, %s)"
            engine.execute(sql, (username, stop_id))
            flash('Congrats! you have added this stop into Myroutes', 'success')

        stop_num = stop_id
        return render_template('bus_stop.html', **locals())

    return render_template('stop_search.html', **locals())


# =================================== API ==================================#
# An API is used to allow the website to dynamically query the DB without
# having to be refreshed.

#   - /api/routes/all_routes             -> returns all route information
#   - /api/routes/routenum/direction     -> returns all stops associated with route in a given direction
#   - /api/routes/stations               -> returns all stations (Luas, Dart, Bike)
#   - /api/routes/stops                  -> returns all stops for the stop_search autocomplete
# --------------------------------------------------------------------------#


@app.route('/api/all_routes/', methods=['GET'])
def get_route_info():
    return api().bus_route_info()


# --------------------------------------------------------------------------#


@app.route('/api/routes/<string:routenum>/<string:direction>/', methods=['GET'])
def get_stop_info(routenum, direction):
    return api().bus_stop_info_for_route(routenum, direction)


# --------------------------------------------------------------------------#


@app.route('/api/stations/', methods=['GET'])
def get_all_info():
    return api().all_stop_info()


# --------------------------------------------------------------------------#


@app.route('/api/stops/', methods=['GET'])
def get_all_stop_info():
    return api().all_bus_stop_info()


# --------------------------------------------------------------------------#
@app.route("/api/bike_data")
def get_bikes():
    bikes = dbi().bikes()
    return json.dumps(bikes)


# =================================== DB ==================================#



URI = "bikesdb.cvaowyzhojfp.eu-west-1.rds.amazonaws.com"
PORT = "3306"
DB = "All_routes"
USER = "teamgosky"
PASSWORD = "teamgosky"


def connect_to_database():
    db_str = "mysql+mysqldb://{}:{}@{}:{}/{}"
    engine = create_engine(db_str.format(USER, PASSWORD, URI, PORT, DB), echo=True)
    return engine


def get_db():
    engine = getattr(g, 'engine', None)
    if engine is None:
        engine = g.engine = connect_to_database()
    return engine


# =================================== DB ==================================#
app.secret_key = 'secret123'
# Setting app to run only if this file is run directly.
if __name__ == '__main__':
    app.run(debug=True)