import numpy as np
import pandas as pd
import pymc3 as pm
from pymc3.ode import DifferentialEquation
from scipy.integrate import odeint
import arviz as az
import theano
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import timedelta, datetime
from scipy.optimize import minimize
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from Simulations_COVID19 import utilitis
from .utilitis import data_loader as data_loader

class phenom_simulator(data_loader):
    def __init__(self, countries, phenom_constrains = [1, 2, 100, 70, 15000, 20000], data_table = None, load_flag = 'neherlab'):
        
        self.countries = countries
        
        self.trace = {}
        
        self.post_pred = {}

        self.phenom_constrains = {'c1M':phenom_constrains[0],
                          'c1s':phenom_constrains[1],
                          'c2M':phenom_constrains[2],
                          'c2s':phenom_constrains[3],
                          'c3M':phenom_constrains[4],
                          'c3s':phenom_constrains[5]}

        self.load_flag = load_flag
        self.path = '../covid19_scenarios_data/case-counts/'
        self.get_geo_loc = True
        self.location = 'classic'

        if data_table is not None:
            self.get_data_from_object(data_table)
        else:
            if self.load_flag == 'neherlab':
                self.collect_data_neherlab(path=self.path, get_geo_loc = self.get_geo_loc)
            else:
                self.data_read = {}
                for field in ['Confirmed','Recovered','Deaths']:
                    self.recover_data(field)
            self.get_data_from_object(self.load_data(self.countries))
            self.data_read = []

    def get_data_from_object(self, data_table):
        countries_list = self.countries
        if type(countries_list) is not list:
            countries_list = [self.countries] 
        self.data = data_table[data_table["country"].isin(countries_list)]
        if self.load_flag == 'neherlab':
            if self.location == 'classic':
                self.location = ['Full Country']*len(countries_list)

            self.data = self.data[self.data["location"].isin(self.location)]

            self.data['Country'] = self.data["country"]+', '+ self.data["location"]

            self.countries = self.data['Country'].unique()
        return self.data
        
    def phenom_model(self, method, field = 'deaths'):
        for i, country in enumerate(self.countries):
            self.models = {} 
            self.models[method] = {}
            with pm.Model() as model:
                print('phenom_constrains:', self.phenom_constrains,'\n')

                const = {}
                for cn in ['c1','c2','c3']:
                    grp = pm.Normal(cn+'grp', self.phenom_constrains[cn+'M'], self.phenom_constrains[cn+'s'])
                    # Group variance
                    grp_sigma = pm.HalfNormal(cn+'grp_sigma', self.phenom_constrains[cn+'s'])
                    # Individual intercepts
                    const[cn] = pm.Normal(cn,  mu=grp, sigma=grp_sigma,  shape=len(self.countries))

                sigma = pm.HalfNormal('sigma', 10000., shape=len(self.countries))

                temp = self.data[self.data['Country'] == country][field].values
                x = pm.Data("x",  np.arange(0, len(temp)))
                cases = pm.Data("y",  temp)

                # Likelihood
                if method == 'log-model':
                    pm.NegativeBinomial(
                        country, 
                        const['c3'][i]*(1/(1 + np.exp(-(const['c1'][i] * (-const['c2'][i] + x))))),
                        sigma[i], 
                        observed=cases)
                    
                if method == 'gompertz-model':
                    pm.NegativeBinomial(
                        country, 
                        const['c3'][i]*np.exp(-np.exp(-const['c1'][i]*(x-const['c2'][i]))),
                        sigma[i], 
                        observed=cases)
            self.models[method][country] = model
        return models
                        
    def sample_model(self, method = 'log-model', field = 'deaths', **kwargs):
            models = self.phenom_model(method, field)
            self.traces = {} 
            self.traces[method] = {}
            for i, country in enumerate(self.countries):
                self.traces[method][country] = pm.sample_smc(model = models[method][country], **kwargs)
                #marginal_likelihood = model.marginal_log_likelihood
            return models, self.traces #, marginal_likelihood
        
    def sample_posterior_predictive_model(self, method = 'log-model', field = 'deaths', samples = 1000, number_days = 100, **kwargs):
        models, _ = self.sample_model(method = method, field = field, **kwargs)
        self.post_preds = {}
        self.post_preds[method] = {}
        for country in self.countries:
            with model:

                # Update data so that we get predictions into the future
                x_data = np.arange(0, number_days)
                y_data = np.array([np.nan] * len(x_data))
                pm.set_data({"x": x_data})
                pm.set_data({"y": y_data})

                # Sample posterior predictive
                self.post_preds[method][country] = pm.sample_posterior_predictive(self.traces[method][country], samples = samples)
        return self.post_preds
        
    def res_values(self, values, flag_res):
        res = values
        if flag_res:
            values_dif = np.roll(values, -1) - np.roll(values, 1)
            res = np.roll(values_dif, 0)/np.roll(values_dif, 1)
        return res

    def func_sig(self, X, flag_res, *p):
        if flag_res:
            c1,c2,c3 = p
            AB = np.exp(c1*c2)
            A = np.exp(c1)
            AX = np.exp(c1*X)
            model = (A*AB+AX) / (AB + A*AX)
        else:
            c1,c2,c3 = p
            model = c3*(1/(1 + np.exp(-(c1 * (-c2 + X)))))
        return model
    
    def plot_results(self, method, figsize = (17,7), field = 'deaths', Dates = None, ylim = [0, 20000], xlim = [0, 100], ylabel = 'Number of fatalities', flag_res = False, style_color = 'dark_background', time_field = 'time'):
        plt.style.use(style_color)            
        fig = plt.figure(figsize=figsize)
        colors = plt.cm.rainbow(np.linspace(0, 1, len(self.countries)))
        
        for i, country in enumerate(self.countries):
            self.plot_country(method, country, field = field, time_field = time_field, flag_res = flag_res, color = colors[i])
            
            cn = country
            if country == 'China':
                cn = 'Hubai'
            
            if Dates is not None:  
                if cn in Dates.keys():
                    for key, value in Dates[cn].items():
                        ind = np.argwhere(self.data[self.data['Country'] == country]['Date'] == key)[0][0]
                        plt.plot([ind,ind],[0,30000], value[1], label = cn+'-'+ value[0], color=colors[i])
        
        number_days = int(self.post_pred[method+'-'+field][country].shape[1])
        Date = self.data[self.data['Country'] == country]['Date'].iloc[0]
        Date = Date[0:-2]+'20'+Date[-2:]
        list_dates = utilitis.date_list(Date, number_days)
        
        x_ticks = np.arange(0, number_days, np.ceil(number_days*0.1))   
        list_dates = np.array(list_dates)[x_ticks.astype(int)]
        plt.xticks(x_ticks, list_dates, rotation = 45)

        #plt.xlabel('# Days from countries first death report')
        plt.ylabel(ylabel)
        plt.ylim(ylim)
        plt.xlim(xlim)
        return fig
        
    def plot_country(self, method, country, field = 'deaths', time_field = 'time', flag_res = False, color = 'r'):
        plt.scatter(self.data[self.data['Country'] == country][time_field], self.res_values(self.data[self.data['Country'] == country][field], flag_res), color=color                   
                    , edgecolors='black', linewidth=0.3,
                    label = country+' confirmed data', zorder=200)
                    
        plt.scatter(self.data[self.data['Country'] == country][time_field].iloc[-1], self.res_values(self.data[self.data['Country'] == country][field].iloc[-1], flag_res), color=color
                    , edgecolors='white', linewidth=1
                    , label = country+' today',zorder=200, marker = '*', s = 100)
        plt.plot(np.arange(0, self.post_pred[method+'-'+field][country].shape[1]), self.res_values(self.post_pred[method+'-'+field][country], flag_res).T, alpha=0.2, color=color)


    def traces_to_multivariateGrid(self, method, field = 'deaths', colors_dic =False):

        if method == 'log-model':
            clabel = {'c1':'Growth','c2':'Inflexion day for ','c3':'Total number of deaths'}

        if method == 'gompertz-model':
            clabel = {'c1':'Growth','c2':'Displacement','c3':'N'}
        
        for k, cn in enumerate([['c1','c2'],['c3','c1'],['c3','c2']]):
            dfs = []
            for i, country in enumerate(self.countries):
                df = pd.DataFrame(np.append(self.trace[method+'-'+field][cn[0]][:, i],self.trace[method+'-'+field][cn[1]][:, i]).reshape(2,-1).T, columns=[clabel[cn[0]],clabel[cn[1]]])
                df['country'] = country
                dfs += [df]
            df=pd.concat(dfs)
            utilitis.multivariateGrid(clabel[cn[0]], clabel[cn[1]], 'country', df=df, k_is_color = colors_dic) 




            