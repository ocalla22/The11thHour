#------------------------------------------------------------------------------#
#------------------------------IMPORTS-----------------------------------------#
#------------------------------------------------------------------------------#

#https://docs.python.org/3/library/concurrent.futures.html
#from concurrent.futures import ThreadPoolExecutor #not needed
from concurrent.futures import ProcessPoolExecutor

from datetime import date

#conda install -c conda-forge geopandas
#http://geopandas.org/
from geopandas import GeoDataFrame
from geopandas import sjoin

#https://pandas.pydata.org/pandas-docs/stable/
import pandas as pd

#http://numba.pydata.org/numba-doc/dev/user/vectorize.html
from numba import vectorize, float64, int64

#http://www.numpy.org/
import numpy as np

#https://pypi.python.org/pypi/tqdm
from tqdm import tqdm

#https://docs.python.org/3/library/os.html
from os import getcwd
from os import listdir
from os import makedirs
from os import path

#http://toblerity.org/shapely/shapely.geometry.html
from shapely.geometry import Point

#http://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html
from sklearn import preprocessing

#sklearn.ensemble.RandomForestRegressor
from sklearn.ensemble import RandomForestRegressor

#http://scikit-learn.org/stable/modules/model_persistence.html
from sklearn.externals import joblib

#http://scikit-learn.org/stable/modules/classes.html#module-sklearn.metrics
from sklearn.metrics import explained_variance_score
from sklearn.metrics import r2_score #this can be negative, see docs!
from sklearn.metrics import mean_squared_error
from sklearn.metrics import mean_absolute_error
from sklearn.metrics.classification import accuracy_score

#http://scikit-learn.org/stable/modules/classes.html#module-sklearn.model_selection
from sklearn.model_selection import GridSearchCV 
from sklearn.model_selection import train_test_split

#http://scikit-learn.org/stable/modules/classes.html#module-sklearn.pipeline
from sklearn.pipeline import make_pipeline

#https://docs.python.org/3.6/library/time.html
from time import time

#https://docs.python.org/3.1/library/warnings.html
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

#------------------------------------------------------------------------------#
#------------------------------NumbaFuncs--------------------------------------#
#------------------------------------------------------------------------------#

@vectorize([float64(int64,int64), float64(float64, int64)])
def division(time, stops): return time/stops

@vectorize([float64(float64,float64,float64, float64)], nopython=True)
def distance(x1,y1,x2,y2): return ((x1-x2)**2 + (y1-y2)**2)**0.5 

#------------------------------------------------------------------------------#
#------------------------------CLASSES-----------------------------------------#
#------------------------------------------------------------------------------#

'''All classes here can be seen as a wrapper for their methods.
This section is concerned with operating on data and avoids logic related to
saving and reading files'''    
 
class cleaning:
    #https://data.dublinked.ie/dataset/dublin-bus-gps-sample-data-from-dublin-city-council-insight-project
    '''Class that carries out cleaning action on a dataframe.
     - initialised with a pandas dataframe of raw Dublin Bus AVL data
     - assumes column names from DublinBus AVL data
     - single attribute 'df'
     - calls the 'clean' method to execute all other methods in order '''
    #--------------------------------------------------------------------------#

    def __init__(self, df):
        '''initialses dataframe as df, and sets columns'''
        self.df = df
        columns   = ['Timestamp', 'LineID', 'Direction', 'Journey_Pattern_ID', 
                    'Timeframe',  'Vehicle_Journey_ID', 'Operator', 
                    'Congestion', 'Lon', 'Lat', 'Delay', 'Block_ID',
                    'Vehicle_ID', 'Stop_ID', 'At_Stop']
        self.df.columns = columns
    
    #--------------------------------------------------------------------------#
    
    def drop_useless_columns(self):
        '''drops poorly defined, un-used, non-critical columns'''
        useless = ['Congestion',  #ambiguous definition and behaviour
                   'Delay',       #ambiguous definition and behaviour
                   'Block_ID',    #ambiguous definition and behaviour
                   'Operator',    #not used in analysis
                   'Direction']
        self.df = self.df.drop(useless, axis=1)
    
    #--------------------------------------------------------------------------#
    
    def keep_stop_info(self):
        '''drop entries between stops'''
        self.df = self.df[self.df.At_Stop == 1]
        self.df = self.df.drop(['At_Stop'], axis=1)
    
    #--------------------------------------------------------------------------#
    
    def drop_duplicates(self):
        '''drops duplicates standard'''
        self.df = self.df.drop_duplicates(keep='first')
        
    #--------------------------------------------------------------------------#
    
    def fix_journey_pattern_id(self):
        '''takes nulls in Journey Patter ID and re-derives them using this method'''
        single_journeys = [ 'LineID', 'Vehicle_Journey_ID', 'Vehicle_ID' ]
        grouped_df = self.df.groupby(single_journeys, sort=False)
            
        def re_derive_nulls(df):
            '''if there are 2 Journey Pattern IDs  AND one is null AND other is valid,
             reassign whole group to valid the Journey Pattern ID'''
            options =set(df.Journey_Pattern_ID.unique()) 
            if len(options) == 2 and 'null' in options:
                options.remove('null')
                valid = options.pop()
                df.Journey_Pattern_ID = valid
            return df
          
        self.df =  grouped_df.apply(re_derive_nulls).reset_index()
        
    #--------------------------------------------------------------------------# 
    
    def drop_literal_nulls(self):
        '''drops rows where Journey Pattern ID is not 'null' str literal'''
        self.df = self.df[self.df.Journey_Pattern_ID != 'null' ]
        
    #--------------------------------------------------------------------------#
    
    def fix_line_id(self):
        '''Re-derives LineID from Journey Pattern ID. first indices [0-4)'''
        self.df.Journey_Pattern_ID = self.df.Journey_Pattern_ID.astype('str')
        self.df.LineID = self.df.Journey_Pattern_ID.str[:4]
        self.df.LineID = self.df.LineID.str.lstrip('0') #strips leading zeros
   
   
    def create_direction_and_sequenceing(self):
        '''merges route seq data frame onto self.df'''
        seq_df = pd.read_hdf('route_seq.h5')
        columns_used = ['LineID','Direction', 'Stop_ID', 'Stop_Sequence', 'Max_Stop_Sequence']
        seq_df = seq_df[columns_used]
        
        def one_direction(df):
            return (df[df.Direction == 2], df)[len(df.Direction.unique())==1]
        
        seq_df = seq_df.groupby(['LineID','Stop_ID']).apply(one_direction)
        seq_df.Stop_ID = seq_df.Stop_ID.astype(int)
        self.df.Stop_ID = self.df.Stop_ID.astype(int)
        shared_columns = ['LineID', 'Stop_ID']
        self.df = pd.merge(self.df, seq_df, how = 'inner', on = shared_columns)
   
    #--------------------------------------------------------------------------#
    
    def remove_ideling(self):
        '''removes repeats for stop id due to dwell time'''
        
        def remove_journey_ideling(df):
            '''keeps first entry at bus stop for journey'''
            df =df.sort_values('Timestamp')
            return  df.drop_duplicates(subset='Stop_ID', keep='first')
        
        def remove_lat_lon_ideling(df):
            '''used when geopandas sjoin is used'''
            df = df.sort_values('Timestamp')
            df = df.drop_duplicates(subset = ['Lat', 'Lon'], keep='first')
            return df
        
        single_journies = ['Vehicle_Journey_ID','LineID', 'Direction', 'Timeframe']
        self.df = self.df.groupby(single_journies).apply(remove_journey_ideling).reset_index(drop=True)
        #self.df = self.df.groupby(single_journies).apply(remove_lat_lon_ideling).reset_index(drop=True)
     
    #--------------------------------------------------------------------------#
    
    def lat_lon_matching(self): #For Future Use
        ''' merges processed N.T.A. DublinBus stop info with raw data for
        resolving stop positions and stopIDs and sequence.
        -takes entries within catchment radius in degrees. 1deg~111km
        -enhances data quality but does not significantly improve results
        -does not change readouts significantly on front end.
        -takes a long time to run. --Not worth it.--'''
        
        def empty_df():
            '''helps handle occasional goepandas sjoin error in a groupby
            where sjoin is expected to return an empty dataframe, it instead fails
            this constructs the empty df allowing all the results of 
            'groupby(x).apply(closest_stop) to be re_concatenated into 1 df'''
            
            columns = ['Lat_left', 'Lon_left', 'Stop_Sequence', 'geometry',
                       'index_right','index', 'Timestamp', 'LineID', 'Direction',
                       'Journey_Pattern_ID', 'Vehicle_Journey_ID', 'Lon_right',
                       'Lat_right', 'Vehicle_ID'] #column structure of 'combined'            
            return  pd.DataFrame(columns=columns)
        
        def init_geo_df(df):
            '''inits geodf given source df with Lat Lon attributes'''
            crs = {'init': 'epsg:4326'}
            geometry = [Point(xy) for xy in zip(df.Lon, df.Lat)]
            return GeoDataFrame(df, crs=crs, geometry=geometry)
        
        seq_df= pd.read_hdf('route_seq.h5')
        seq_df = seq_df[['LineID', 'Lat', 'Lon', 'Direction','Stop_Sequence']]
        seq_df.LineID = seq_df.LineID.astype('str')
        seq_df = init_geo_df(seq_df)
        seq_df.geometry = seq_df.geometry.buffer(0.001) #catchment radius for stop, in degrees
        self.df = init_geo_df(self.df)
                                           
        def closest_stop(df):
            '''maps each row for route and direction permutation to...
             nearest valid stop within that route-direction set'''
            route = df.LineID.unique()[0]
            direction = df.Direction.unique()[0]
            seq_df2 = seq_df[(seq_df.LineID==route) & (seq_df.Direction==direction)]
            seq_df2 = seq_df2.drop(['LineID','Direction'], axis = 1)
            try:
                combined = sjoin(seq_df2, df, how='inner', op='intersects')
                return combined
            except: 
                print('viva la excepcion!')
                return empty_df() #I handle the geopandas empty array error!    
        
        pattern = ['LineID', 'Direction']
        self.df = self.df.groupby(pattern, sort=False).apply(closest_stop).reset_index(drop=True) 
        self.df['dist'] = distance(self.df.Lat_left.values,  self.df.Lon_left.values, 
                                   self.df.Lat_right.values, self.df.Lon_right.values)
        
        def closest_entry(df):
            '''takes rows for each journey that minimise distance to local stop'''
            df.sort_values(['dist'])
            return df[df.dist == df.dist.min()]
        
        single_journeys = ['Journey_Pattern_ID','Vehicle_Journey_ID',
                           'Vehicle_ID', 'Stop_Sequence']
        self.df = self.df.groupby(single_journeys, sort=False).apply(closest_entry).reset_index(drop=True)
        
    #--------------------------------------------------------------------------#
    
    def clean(self):
        '''executes above instructions'''
        self.drop_useless_columns()
        self.keep_stop_info()
        self.drop_duplicates()
        self.fix_journey_pattern_id() 
        self.drop_literal_nulls()    
        self.fix_line_id()         
        self.create_direction_and_sequenceing()
        self.remove_ideling()
        #self.lat_lon_matching() # todo: I take too long,
        return self.df
        
#------------------------------------------------------------------------------#

class preparing:
    '''class 
s dataframe with derived columns necessary for modeling
    - single attribute 'df' 
    - 'prepare' method carries out operations in order'''

    def __init__(self, dataframe):
        '''initialises dataframe as df'''
        self.df = dataframe
        
    #--------------------------------------------------------------------------#

    def create_time_categories(self):
        '''creates Time, Day, Hour and Time Bin Start
        - Time bin start represents different 15 minute periods of the day
        - Deletes intermediate columns that are not re-used'''
        self.df['Time'] = pd.to_datetime(self.df.Timestamp, unit='us')
        self.df['Day_Of_Week'] = self.df.Time.dt.dayofweek
        self.df['Hour'] = self.df.Time.dt.hour.astype('str')
                
        def make_time_bin_start(df):
            '''creates Time Bin Start and drops intermediate columns'''
            df['Minute'] = df.Time.dt.minute
            df['Min_15'] = np.where((df.Minute > 15), '1', '0')
            df['Min_30'] = np.where((self.df.Minute > 30), '1', '0')
            df['Min_45'] = np.where((self.df.Minute > 45), '1', '0')
            time_list = ['Hour', 'Min_15', 'Min_30', 'Min_45']
            df['Time_Bin_Start'] = df[time_list].apply(lambda x: ''.join(x), axis=1)
            df = df.drop(['Minute', 'Min_15', 'Min_30','Min_45'], axis = 1)
            return df
        
        self.df = make_time_bin_start(self.df)
        self.df = self.df.drop(['Hour'], axis=1)
     
    #--------------------------------------------------------------------------#   
    
    def create_start_end_times(self):
        '''creates start times and end times and journey times columns for df'''
        as_delta = pd.to_timedelta
        single_journeys = ['Vehicle_Journey_ID', 'Vehicle_ID', 'Journey_Pattern_ID']
        grouped_df = self.df.groupby(single_journeys, sort=False)
        self.df['End_Time'] = grouped_df['Timestamp'].transform(max)
        self.df['Start_Time'] = grouped_df['Timestamp'].transform(min)
        self.df['Journey_Time'] = self.df.End_Time - self.df.Start_Time
        self.df.Journey_Time = as_delta(self.df.Journey_Time, unit='us').astype('timedelta64[m]')
    
    #--------------------------------------------------------------------------#
    
    def drop_impossible_journey_times(self):
        '''returns rows where journey times are greater than zero'''
        self.df = self.df[self.df.Journey_Time > 0]
        self.df = self.df[self.df.Journey_Time < 120]
        
    #--------------------------------------------------------------------------#
    
    def create_start_end_stops(self):
        '''creates start and end stops and the difference between them'''
        single_journeys = ['Vehicle_Journey_ID', 'Vehicle_ID', 'Journey_Pattern_ID']
        grouped_df = self.df.groupby(single_journeys, sort=False)
        self.df['End_Stop'] = grouped_df['Stop_Sequence'].transform(max)
        self.df['Start_Stop'] = grouped_df['Stop_Sequence'].transform(min)
        self.df['Journey_Length'] = self.df.End_Stop - self.df.Start_Stop
            
    #--------------------------------------------------------------------------#       

    def create_holiday(self):
        '''creates bool column if date corresponds to a school holiday'''
        date_before = date(2012, 12, 31)
        date_after = date(2013, 1, 5)
        self.df['Holiday'] = np.where((self.df.Time.dt.date < date_after)  \
                                    & (self.df.Time.dt.date > date_before), 1, 0)
    
    #--------------------------------------------------------------------------#

    def create_scheduled_time_op(self):
        '''merges route_times with df to create scheduled time op column'''
    
        def get_times_dataframe():
            '''retrieves and prepares times dataframe'''
            times_dataframe = pd.read_hdf('route_times.h5')
            times_dataframe = times_dataframe.rename(columns={'Route':'LineID'})
            times_dataframe = times_dataframe[['LineID', 'Scheduled_Time_OP']]
            return times_dataframe
            
        self.df = pd.merge(self.df, get_times_dataframe(), how='inner', on=['LineID'])
                   
    #--------------------------------------------------------------------------#
    
    def drop_impossible_journey_lengths(self):
        '''if a journey has no stop delta it cannot be measured and thus is invalid'''
        self.df = self.df[self.df.Journey_Length > 0]
        
    #--------------------------------------------------------------------------#
    
    def create_travel_stops_and_times(self):
        '''creates columns measuring number of stops left (FEATURE)
         and time remaining (TARGET FEATURE), for journey'''
        as_delta = pd.to_timedelta
        self.df['Time_To_Travel'] = self.df.End_Time - self.df.Timestamp
        self.df.Time_To_Travel = as_delta(self.df.Time_To_Travel, unit='us').astype('timedelta64[m]')
        self.df['Stops_To_Travel'] = (self.df.End_Stop.astype(int) - self.df.Stop_Sequence.astype(int))
    
    #--------------------------------------------------------------------------#
    
    def keep_last(self):
        '''keeps journeys that reach last three stops'''
        self.df = self.df[(self.df.End_Stop + 3  <= self.df.Max_Stop_Sequence)]
        
    #--------------------------------------------------------------------------#
    
    def create_speeds_per_stop(self):
        '''creates scheduled speed which is the scheduled mean rate of stop traversal'''
        self.df['Scheduled_Speed_Per_Stop'] = division(self.df.Scheduled_Time_OP.values, 
                                                       self.df.Max_Stop_Sequence.values)
        
    #--------------------------------------------------------------------------#
    
    def create_weather_columns(self):
        '''creates weather columns such as temerature and windspeed
        merges weather info with df by timestamp'''
        def get_weather_dataframe():
            '''gets weather dataframe and prepares it for merge'''
            weather_dataframe = pd.read_hdf('weather.h5')
            weather_dataframe['Time'] = pd.to_datetime(weather_dataframe['Time'])
            weather_dataframe.sort_values(['Time'], ascending=[True], inplace=True)
            weather_dataframe['Hour_Of_Day'] = weather_dataframe['Time'].dt.hour
            weather_dataframe.sort_values(['Time'], ascending=[True], inplace=True)
            return weather_dataframe
        
        self.df.sort_values(['Time'], ascending=[True], inplace=True)
        self.df =  pd.merge_asof(self.df, get_weather_dataframe(), on='Time')
        
    #--------------------------------------------------------------------------#
    
    def drop_non_modeling_columns(self):
        '''drops columns that can't be modeled,
        keeps coluumns that are essential for further data handling'''
        useful = ['LineID', 'Vehicle_Journey_ID', 'Vehicle_ID','Timestamp','Timeframe', #grouping
                  
                  'Journey_Length','Journey_Time', #mean speed
                  
                  'Direction', 'Day_Of_Week', 'Time_Bin_Start', #Rf Features
                  'Wind_Speed', 'Temperature', 
                  'Holiday', 'Scheduled_Speed_Per_Stop',
                  'Stops_To_Travel', 'Stop_Sequence', 
                  
                  'Time_To_Travel'] #target feature
        self.df = self.df = self.df[useful]
    
    #--------------------------------------------------------------------------#
   
    def prepare(self):
        '''applies predefined preparation methods'''
        self.create_start_end_stops()  
        self.create_time_categories()
        self.create_start_end_times()      
        self.drop_impossible_journey_times() 
        self.create_holiday()              
        self.create_scheduled_time_op()        
        self.create_travel_stops_and_times() 
        self.drop_impossible_journey_lengths() 
        self.keep_last()
        self.create_speeds_per_stop()      
        self.create_weather_columns()
        self.drop_non_modeling_columns()
        return self.df

#------------------------------------------------------------------------------#
    
class extracting:
    '''class for separating data by route
    - relies on re_con folder of reconstructed data'''
    
    def __init__(self):
        path_to_folder = path.join(getcwd(), 're_con')
        all_files = listdir(path_to_folder)
        path_to_files = list(map(lambda data: path.join(path_to_folder, data), all_files))
        self.files = path_to_files
        
    #--------------------------------------------------------------------------#
    
    def extract(self, route):
        '''extracts single route from files and returns df of that route
        read and write to hdfs for speed'''
        accumulator = []
        for data in self.files:
            df = pd.read_hdf(data)
            df = df[df.LineID == route].drop(['LineID'], axis=1)
            accumulator.append(df)
        df = pd.concat(accumulator, axis = 0).reset_index()
        return df
    
    #--------------------------------------------------------------------------#
    
    def drop_outliers(self, df):
        '''keep lower 95% of data'''
        return df[df.Journey_Time <= df.Journey_Time.quantile(0.95)]
    
    #--------------------------------------------------------------------------#
    
    def make_mean_speed(self, df):
        #https://en.wikipedia.org/wiki/Harmonic_mean
        #avg_speed = hmean(avg_speeds) = n/(sum(1/avg_speeds))
        '''calculates expected rate of stop traversal at for...
        a route-direction at a given time'''
        dir_time = ['Direction', 'Day_Of_Week','Time_Bin_Start']
        df['recip_Journey_Speed'] =  division(df.Journey_Time.values, df.Journey_Length.values)
              
        def mean_speed_at_time(df):
            '''calculates mean speed for each journey on given day at given time
            Speed computed with harmonic mean of mean speeds for each journey'''
        
            single_journeys = ['Vehicle_Journey_ID', 'Vehicle_ID','Timeframe']
            undersampled = df.groupby(single_journeys).first()
            df['Speed_At_Time'] = 1/undersampled.recip_Journey_Speed.mean()
            return df
        
        df = df.groupby(dir_time, sort=False).apply(mean_speed_at_time).reset_index(drop=True)
        return df
    
    #--------------------------------------------------------------------------#
              
    def extract_and_analyse(self, route):
        '''applies above methods in order'''
        df = self.extract(route)
        df = self.drop_outliers(df)
        df = self.make_mean_speed(df)
        return df

#------------------------------------------------------------------------------#

class modelling:
    '''class that contains processes for modeling
    - trains models on data
    - records model metrics for identical test sets for rf, ms, db''' 
    
    def __init__(self):
        '''creats columns for record dataframe'''
        self.metric_columns = ['route', 'r2', 'exp_variance', 'rmse', 'mae', 
                               'five_pc_margin','ten_pc_margin', 
                               'twenty_five_pc_margin', 'fifty_pc_margin',
                               'two_half_min_delta','five_min_delta','ten_min_delta',
                               'five_min_late']
        
        self.target = ['Time_To_Travel']
        
        self.features = ['Direction', 'Day_Of_Week', 'Time_Bin_Start', 'Wind_Speed', 
                        'Temperature', 'Holiday', 'Stops_To_Travel','Stop_Sequence']
       
        self.excess = ['Scheduled_Speed_Per_Stop', 'Speed_At_Time']
        
        self.record_rf = pd.DataFrame(columns=self.metric_columns)
        self.record_db = pd.DataFrame(columns=self.metric_columns)
        self.record_ms = pd.DataFrame(columns=self.metric_columns)
    
    #--------------------------------------------------------------------------#
    
    def create_train_test_sets(self, data):
        '''create train test set storing splits as attributes'''
        data.Time_Bin_Start = data.Time_Bin_Start.astype('str')
        self.X_train, self.X_test, self.y_train, self.y_test = \
        train_test_split(data, np.ravel(data[self.target]),
                        test_size=0.2, random_state=33)
    
    #--------------------------------------------------------------------------#
    
    def create_rf_model(self):
        '''creates rf regressor for data,
        preprocessing, and hyper parameters are costly to training time
        they only provide marginal gains to accuracy'''
        scaler = preprocessing.StandardScaler()
        scaler = scaler.fit(self.X_train[self.features]) #normalisation
        pipeline = make_pipeline(preprocessing.StandardScaler(), 
                                 RandomForestRegressor(n_estimators=10, n_jobs=1))
        hyperparameters = {'randomforestregressor__max_features':[ None, 'sqrt'],
                           'randomforestregressor__max_depth':[None, 5, 3]}
        regressor = GridSearchCV(pipeline, hyperparameters, cv=8)
        regressor.fit(self.X_train[self.features], self.y_train)
        self.model = regressor
        
    #--------------------------------------------------------------------------#

    def create_test_metrics(self, estimator):
        '''takes most recently created rf regressor and creates test metrics for it
        takes estimator DB or MS to create metrics for DB and Mean speed models'''
        actual = self.y_test
        
        def choose_model(estimator):
            '''creates results for specified model'''
            df = pd.DataFrame(self.X_test)
            if estimator == 'DB':
                return df.Stops_To_Travel * df.Scheduled_Speed_Per_Stop
            elif estimator == 'RF':
                return self.model.predict(self.X_test[self.features])
            elif estimator == 'MS':
                return   df.Stops_To_Travel /  df.Speed_At_Time
            else:    
                print('Invalid: Choose either', 'RF', 'DB','MS')                    
        
        def manipulate_dataframe(estimations): #rf_pred OR db_pred
            '''prediction column is assigned to estimations
            tolerance columns are defined'''
            df = pd.DataFrame(self.X_test)
            df['actual'] = actual
            df['predicted'] = estimations
            df['delta'] = df.actual - df.predicted
            df['margin'] = df.delta/df.actual
            df['five_pc_margin'] = np.where(abs(df.margin) <= 0.05, 1, 0)
            df['ten_pc_margin'] =  np.where(abs(df.margin) <= 0.1, 1, 0)
            df['twenty_five_pc_margin'] = np.where(abs(df.margin) <= 0.25, 1, 0)
            df['fifty_pc_margin'] = np.where(abs(df.margin) <= 0.5, 1, 0)
            df['two_half_min_delta'] = np.where(abs(df.delta) <= 2.5, 1, 0)
            df['five_min_delta'] = np.where(abs(df.delta) <= 5, 1, 0)
            df['ten_min_delta'] = np.where(abs(df.delta) <= 10, 1, 0)
            df['five_min_late'] = np.where( (df.delta) <= 5, 1, 0)
            df['true'] = 1
            return df
        
        def assign_metrics(estimations): #rf_pred OR db_pred
            '''scores are based on either Db or Rf depending on current and previous input'''
            self.rsquared =  r2_score(actual, estimations)
            self.rmse = mean_squared_error(actual, estimations)**0.5
            self.mae = mean_absolute_error(actual, estimations)
            self.exp_var = explained_variance_score(actual, estimations)
            self.five_pc = accuracy_score(data.true, data.five_pc_margin)
            self.ten_pc = accuracy_score(data.true, data.ten_pc_margin)
            self.twenty_five_pc = accuracy_score(data.true, data.twenty_five_pc_margin)
            self.fifty_pc = accuracy_score(data.true, data.fifty_pc_margin)
            self.two_half_min = accuracy_score(data.true, data.two_half_min_delta)
            self.five_min = accuracy_score(data.true, data.five_min_delta)
            self.ten_min = accuracy_score(data.true, data.ten_min_delta)
            self.five_min_late = accuracy_score(data.true, data.five_min_late)
        
        #executes functions defined within this method   
        estimations = choose_model(estimator)  #chooses model  
        data = manipulate_dataframe(estimations) #makes columns for analysis
        assign_metrics(estimations) #assigns models results from most recent model
        
    #--------------------------------------------------------------------------#
        
    def record_test_metrics(self, route, estimator):
        '''takes most recently evaluated test metrics and stores them in record'''
        values = [route, self.rsquared, self.exp_var, self.rmse, self.mae, 
                  self.five_pc, self.ten_pc, self.twenty_five_pc, self.fifty_pc,
                  self.two_half_min, self.five_min, self.ten_min, self.five_min_late]
        keys = self.metric_columns
        row = dict(zip(keys, values))
        record = pd.DataFrame(data=row, columns=self.metric_columns, index=[route])
        if estimator == 'RF':
            self.record_rf = self.record_rf.append(record)
        elif estimator == 'DB':
            self.record_db = self.record_db.append(record)
        elif estimator == 'MS':
            self.record_ms = self.record_ms.append(record)   
        else:
            print('recorded incorrectly')
    #--------------------------------------------------------------------------#
        
    def model_route(self, data, route):
        '''runs modeling process for a set of data'''
        self.create_train_test_sets(data)
        self.create_rf_model()
        self.create_test_metrics('RF')
        self.record_test_metrics(route, 'RF') #assigned to RF_Record
        self.create_test_metrics('DB')
        self.record_test_metrics(route, 'DB') #assigned to DB_Record
        self.create_test_metrics('MS')
        self.record_test_metrics(route, 'MS')
        return (self.model, self.record_rf, self.record_db, self.record_ms)
 
#------------------------------------------------------------------------------#
#------------------------------Functions---------------------------------------#
#------------------------------------------------------------------------------#

'''this section operates with files, on a close level, it loads files, executes 
cleaning, preparation, extraction and modelling on high level.'''
 
def timing(func):
    '''timing decorator for functions,--cannot be used with multiprocessing--'''
    def wrapper(*arg, **kw):
        '''source: http://www.daniweb.com/code/snippet368.html'''
        t1 = time()
        res = func(*arg, **kw)
        t2 = time()
        return (t2 - t1), res, func.__name__
    return wrapper
        
#------------------------------------------------------------------------------#

def setup_folders():
    '''creates folder for re_con, routes and pkls'''
    for folder in ['routes', 're_con', 'pkls']:
        try:
            path_to_routes_folder = path.join(getcwd(), folder)
            makedirs(path_to_routes_folder, exist_ok=True)
        except:
            print(folder, 'made already')
            
def setup_hdfs():
    '''converts csvs used to hdf, better perf'''
    
    def setup_route_seq_hdf():
        '''drops bi directionals, makes max_stop_sequence, converts to hdf'''
        seq_df = pd.read_csv('route_seq.csv')
        columns_used = ['LineID','Direction','Stop_ID','Stop_Sequence']
        seq_df = seq_df[columns_used]        
        
        def one_direction(df):
            '''returns empty if bidirectional, unchanged if uni directional'''
            return (df[df.Direction == 2], df)[len(df.Direction.unique())==1]
        
        seq_df = seq_df.groupby(['LineID','Stop_ID']).apply(one_direction)
        Journey = ['LineID', 'Direction']
        seq_df['Max_Stop_Sequence'] = seq_df.groupby(Journey).Stop_Sequence.transform(max)
        seq_df.to_hdf('route_seq.h5', key='moo', mode='w')
    
    def setup_times_hdf():
        pd.read_csv('route_times.csv').to_hdf('route_times.h5', key='moo', mode='w')

    def setup_weather_hdf():
        pd.read_csv('weather.csv').to_hdf('weather.h5', key='moo', mode='w')
    
    setup_route_seq_hdf()
    setup_times_hdf()
    setup_weather_hdf()
#------------------------------------------------------------------------------#

def re_construction(data_file):
    path_to_folder = path.join(getcwd(), 'DayRawCopy')
    path_to_file = path.join(path_to_folder, data_file)
    '''executes cleaning and prepatation on raw data files'''
    df = pd.read_csv(path_to_file, converters = {1:str, 13:str}, engine='c')
    df = cleaning(df).clean()
    df = preparing(df).prepare()
    write_address = path.join(getcwd(), 're_con' , data_file[:-4] + '.h5')
    df.to_hdf(write_address, key='moo', mode='w')
    return 'wooot'
    
#------------------------------------------------------------------------------#
    
def get_all_routes():
        '''gets all routes from files'''
        routes = set()
        path_to_folder = path.join(getcwd(), 're_con')
        all_files = listdir(path_to_folder)
        path_to_files = list(map(lambda data: path.join(path_to_folder, data), all_files))
        for data in path_to_files:
            df = pd.read_hdf(data)
            routes = routes.union(set(df.LineID.unique()))
        return routes
    
#------------------------------------------------------------------------------#    
    
def extraction(route):
    '''splits data by route'''
    results = []
    df = extracting().extract_and_analyse(route)
    write_address = path.join(getcwd(), 'routes', 'xbeta'+str(route)+'.h5')
    df.to_hdf(write_address, key='moo', mode = 'w')        
    results.append(route +'it worked!')
    return results

#------------------------------------------------------------------------------#

def quantification(data_file):
    '''takes data_file, makes model object, saves model and returns model stats'''
    path_to_folder = path.join(getcwd(), 'routes')
    path_to_file =  path.join(path_to_folder, data_file)
    route = data_file[5:-3]
    model = modelling()
    rf_reg, *rest  = model.model_route(pd.read_hdf(path_to_file), route) #ready for pkl
    write_address = path.join(getcwd(), 'pkls', str(route)+'rf.pkl')
    joblib.dump(rf_reg, write_address)
    return rest #return test_scores for rf, db, ms respectively

#------------------------------------------------------------------------------#
#-----------------------------Main Methods-------------------------------------#
#------------------------------------------------------------------------------#

''' this section is used for high level execution of tasks using parralelism
it operates on a folder level; taking folders of data and operating on them.'''

def main1(): #IO Bound, Vonneuman Bottleneck -- multi-thread chunks
    '''multiprocesses cleaning and prep of raw data, cpu heavy'''
    path_to_raw = path.join(getcwd(), 'DayRawCopy')
    files = listdir(path_to_raw)
    with ProcessPoolExecutor(max_workers=3) as Executor:
        for file, result in tqdm(zip(files, Executor.map(re_construction, files, chunksize=2))):
            pass

#------------------------------------------------------------------------------#
   
def main2():  #Currently IO, Vonnneuman -- multi-thread chunks
    '''seperates routes into seperate files, ready for training, io heavy'''
    routes = get_all_routes()
    with ProcessPoolExecutor(max_workers=3) as Executor:
        for route, result in tqdm(zip(routes, Executor.map(extraction, routes, chunksize = 2))):
            pass
#------------------------------------------------------------------------------#
    
def main3(): #CPU Bound - sklearn algorithm
    '''prepares a model for each route
    result stores a filename and a tuple of RF,DB model results
    in the final steps these results are gathered and saved'''
    path_to_folder = path.join(getcwd(), 'routes' )
    files = listdir(path_to_folder)
    pool = ProcessPoolExecutor(max_workers=2)
    RF_records, DB_records, MS_records = [], [], []
    results = zip(files, pool.map(quantification, files))
    for data_file, summary in tqdm(results):
        RF_row, DB_row, MS_row = summary
        RF_records.append(RF_row) #collects all RF results
        DB_records.append(DB_row) #collects all DB results
        MS_records.append(MS_row) #collects all MS results
    pd.concat(RF_records, axis=0, ignore_index=True).to_csv('RF_Model_Summary.csv')
    pd.concat(DB_records, axis=0, ignore_index=True).to_csv('DB_Model_Summary.csv')
    pd.concat(MS_records, axis=0, ignore_index=True).to_csv('MS_Model_Summary.csv')
    
#------------------------------------------------------------------------------#
#---------------------------If Run Directly------------------------------------#
#------------------------------------------------------------------------------#
        
if __name__ == '__main__':
    
    @timing
    def processing():
        setup_folders()
        setup_hdfs()
        t1=time()
        main1()
        t2=time()
        print((t2-t1)//60, 'Minutess to re_construct')
        main2()
        t3=time()
        print((t3-t2)//60, 'Minutess to extract')
        main3()
        t4=time()
        print((t4-t3)//60, 'Minutess to quantify')

    processing()
    #print(re_construction('siri.20121106.csv'))```