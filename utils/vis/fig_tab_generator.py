import argparse

import pandas as pd
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import matplotlib.transforms as transforms
import json, codecs
from os.path import join
import datetime
import math


class VisGenerator(object):
    def __init__(self, data_file):
        self._data_file = data_file
        self._df = None
        self.load_data()

    def load_data(self):
        df = pd.read_csv(self._data_file, sep='\t')
        df = df.dropna(how='all')  # remove empty rows
        df['date_admission'] = pd.to_datetime(df['date_admission'], format='%Y-%m-%d')
        mask = (df['date_admission'] > datetime.datetime.strptime('2020-02-01', '%Y-%m-%d')) & (df['not_readmission'] == 1)
        df = df[mask]
        self._df = df

    @staticmethod
    def stat_analyse_numeric(sr, decimal=False):
        sr.replace(regex=True, to_replace=r'[^\d\.]', value=r'', inplace=True)
        sr = pd.to_numeric(sr)
        fmt = '{:.1f} ({:.1f}-{:.1f})' if decimal else '{:.0f} ({:.0f}-{:.0f})'
        return fmt.format(sr.median(), sr.quantile(0.25), sr.quantile(0.75))

    @staticmethod
    def get_value_from_cohort(v, col, cohort):
        if v['type'] == 'numeric':
            need_dec = True if 'decimal' in v and v['decimal'] else False
            return VisGenerator.stat_analyse_numeric(cohort[col], decimal=need_dec)
        elif v['type'] == 'binary':
            return VisGenerator.stat_analyse_binary(cohort[col])

    @staticmethod
    def stat_analyse_binary(sr):
        sum = sr.sum()
        return '{:.0f} ({:.1%})'.format(sum, 1.0 * sum / sr.shape[0])

    def descriptive_table(self, config, binary_cohort_splitter=['death', 'poor_outcome_icu_or_death'],
                          binary_cohort_labels=['N (Did not die + Died)',
                                                'Did not die (n={:d})',
                                                'Died (n={:d})',
                                                'N (Not poor outcome + Poor outcome)',
                                                'Not poor outcome (n={:d})',
                                                'Poor outcome (n={:d})']):
        sub_cohorts = []
        for bs in binary_cohort_splitter:
            sub_cohorts.append(self._df[self._df[bs] == 0])
            sub_cohorts.append(self._df[self._df[bs] == 1])
        ch_ns = [ch.shape[0] for ch in sub_cohorts]
        result = []
        for cat in config:
            c = cat['category']
            vars = cat['variables']
            cat_result = {'category': c, "data": []}
            result.append(cat_result)
            for v in vars:
                col = v['field']
                row = [v['label']]
                idx = 0
                # general population analytics
                row.append(self._df[self._df[col].notna()].shape[0])
                row.append(VisGenerator.get_value_from_cohort(v, col, self._df))
                for cohort in sub_cohorts:
                    if idx % 2 == 0:
                        count = sub_cohorts[idx][sub_cohorts[idx][col].notna()].shape[0]
                        count += sub_cohorts[idx+1][sub_cohorts[idx+1][col].notna()].shape[0]
                        row.append(count)
                    row.append(VisGenerator.get_value_from_cohort(v, col, cohort))
                    idx += 1
                cat_result['data'].append(row)
        headers = ['Category', 'Variable', 'N (all)', 'All (n={:d})'.format(self._df.shape[0]),
                   binary_cohort_labels[0], binary_cohort_labels[1].format(ch_ns[0]),
                   binary_cohort_labels[2].format(ch_ns[1]), binary_cohort_labels[3],
                   binary_cohort_labels[4].format(ch_ns[2]),
                   binary_cohort_labels[5].format(ch_ns[3])]
        print(VisGenerator.format_tab(headers, result))
        return result

    def print_basic_stats(self):
        print(self._df['age'].min(), self._df['age'].max())
        df = self._df
        mask = (df['diabetes_mellitus']==1.0) | (df['chronic_lung_disease'] == 1.0) | (df['immunocompromised'] == 1.0) \
               | (df['malignancy']==1.0 ) | (df['hypertension'] == 1.0) | (df['heart_disease'] == 1.0) | \
               (df['chronic_renal_disease'] == 1.0)
        print('comobidities', df[mask].shape)
        print('Lymphocytopenia: ', df[df['lymphocyte_1'] < 1.5].shape)
        # mask = (df['nppv']==1.0) | (df['hfnc'] == 1.0) | (df['intubation'] == 1.0) | (df['ecmo'] == 1.0)
        mask =  (df['intubation'] == 1.0) | (df['ecmo'] == 1.0)
        print('mechanical ventilation', df[mask].shape)
        mask = mask & (df['death'] == 1)
        print('mechanical ventilation & death', df[mask].shape)

    @staticmethod
    def format_tab(header, result):
        rows = ['\t'.join(header)]
        for cat_r in result:
            rows.append(cat_r['category'])
            for dr in cat_r['data']:
                rows.append('\t'.join([''] + [str(c) for c in dr]))
        return '\n'.join(rows)

    @staticmethod
    def univariate_table(config, cat_file, num_file, multi_file):
        multi_data = pd.read_csv(multi_file)
        uni_queries = {
            "binary": {
                "data_idx": pd.read_csv(cat_file, sep='\t'),
                "filter_col": "case",
                "data_cols": ["odds_ratio", "p_value"],
                "OR_CI": ["OR_CI95_lower", "OR_CI95_upper"],
                "filter_values": ["death", "poor_prognosis"],
                "var_col": "condition"
            },
            "numeric": {
                "data_idx": pd.read_csv(num_file, sep='\t'),
                "filter_col": "outcome",
                "data_cols": ["OR", "p_value"],
                "OR_CI": ["CI_95_lower", "CI_95_upper"],
                "filter_values": ["death", "poor_prognosis"],
                "var_col": "feature"
            }
        }
        multi_queries = {
            "data": multi_file,
            "filter_col": "outcome"
        }
        result = []
        for cat in config:
            c = cat['category']
            vars = cat['variables']
            cat_result = {'category': c, "data": []}
            result.append(cat_result)
            for v in vars:
                col = v['field']
                row = [v['label']]
                uniq = uni_queries[v['type']]
                for fv in uniq['filter_values']:
                    df = uniq['data_idx']
                    fv_data = df[df[uniq['filter_col']] == fv]
                    data_row = fv_data[fv_data[uniq["var_col"]] == col]
                    idx = 0
                    for dc in uniq['data_cols']:
                        v = data_row[dc].iloc[0]
                        if idx == 0:
                            cis = []
                            for ci_col in uniq['OR_CI']:
                                cis.append(data_row[ci_col].iloc[0])
                            v = '{:.3f} ({:.3f};{:.3f})'.format(v, cis[0], cis[1])
                        else:
                            v = '{:e}'.format(v)
                        row.append(v)
                        idx += 1
                cat_result['data'].append(row)
        print(VisGenerator.format_tab(["", "Variable", "Odds ratio (CI at 95%)", "p-value", "Odds ratio (CI at 95%)", "p-value"], result))

    def sankey_diagram(self, output_file):
        nodes = ["Hospitalisation", "ICU Admission", "Non-ICU Wards", "Poor Outcomes", "Mild Outcomes", "Death", "Discharged"]
        hos = set(self._df['name_index'].tolist())
        hos2icu = set(self._df[self._df['days_in_icu'].notnull()]['name_index'].tolist())
        hos2nonicu = hos - hos2icu
        poor_outcomes = set(self._df[self._df['poor_outcome_icu_or_death']>0]['name_index'].tolist())
        mild_outcomes = hos - poor_outcomes
        deaths = set(self._df[self._df['death']>0]['name_index'].tolist())
        # hos2poor = poor_outcomes - hos2icu
        # hos2death = deaths - poor_outcomes - hos2icu
        # hos2dis = hos - hos2death - hos2poor - hos2icu

        icu2death = deaths & hos2icu - poor_outcomes
        icu2poor = poor_outcomes & hos2icu
        icu2mild = hos2icu - icu2poor - icu2death

        nonicu2poor = poor_outcomes - hos2icu
        nonicu2death = deaths - poor_outcomes - hos2icu
        nonicu2mild = hos - nonicu2death - nonicu2poor - hos2icu

        mild2dis = icu2mild | nonicu2mild

        poor2death = poor_outcomes & deaths
        poor2dis = poor_outcomes - poor2death

        links = [
            {"s": "Hospitalisation", "t": "ICU Admission", "n": len(hos2icu)},
            {"s": "Hospitalisation", "t": "Non-ICU Wards", "n": len(hos2nonicu)},
            {"s": "Non-ICU Wards", "t": "Poor Outcomes", "n": len(nonicu2poor)},
            {"s": "Non-ICU Wards", "t": "Death", "n": len(nonicu2death)},
            {"s": "Non-ICU Wards", "t": "Mild Outcomes", "n": len(nonicu2mild)},
            {"s": "ICU Admission", "t": "Poor Outcomes", "n": len(icu2poor)},
            {"s": "ICU Admission", "t": "Death", "n": len(icu2death)},
            {"s": "ICU Admission", "t": "Mild Outcomes", "n": len(icu2mild)},
            {"s": "Mild Outcomes", "t": "Discharged", "n": len(mild2dis)},
            {"s": "Poor Outcomes", "t": "Death", "n": len(poor2death)},
            {"s": "Poor Outcomes", "t": "Discharged", "n": len(poor2dis)}
        ]
        colors = {
            "toICU": "rgba(245, 182, 66, 0.2)",
            "toPoor": "rgba(240, 151, 139, 0.2)",
            "toNonICU": "rgba(124, 159, 191, 0.2)",
            "toDeath": "rgba(105, 81, 78, 0.2)",
            "toMild": "rgba(124, 191, 144, 0.2)",
            "toDischarge": "rgba(124, 191, 144, 0.2)",
            "toDischarge2": "rgba(54, 153, 131, 0.2)"
        }
        s = []
        t = []
        v = []
        for l in links:
            s.append(nodes.index(l['s']))
            t.append(nodes.index(l['t']))
            v.append(l['n'])
        fig = go.Figure(data=[go.Sankey(
            node = dict(
                pad = 15,
                thickness = 20,
                line = dict(color = "black", width = 0.5),
                label = nodes,
                color = ["#f5bc42", "#f57b42", '#425b96', "#f55742", "#829bba", "#61352f", "#37b05b"]
            ),
            link = dict(
                source = s,
                target = t,
                value = v,
                color = [colors['toICU'],
                         colors['toNonICU'], colors['toPoor'], colors['toDeath'], colors['toDischarge'],
                         colors['toPoor'], colors['toDeath'], colors['toMild'], colors['toDischarge'], colors['toDeath'],
                         colors['toDischarge2']]
            ))])

        fig.update_layout(title_text="Pathways of China Cohort", font_size=10)
        # fig.show()
        fig.write_image(output_file)

    @staticmethod
    def prob_lifting_auc(prob_lift_files, labels=None, colors=None):
        aucs = []
        idx = 0
        for plf in prob_lift_files:
            df = pd.read_csv(plf, sep='\t' if plf.endswith('.tsv') else ',')
            name = labels[idx] if labels is not None else plf
            name += ', AUC - {:.3f}'.format(df['roc_auc_score'][0])
            aucs.append({'x': 1 - df['specificity'],
                         'y': df['sensitivity'],
                         'color': None if colors is None else colors[idx],
                         'name': name})
            idx += 1

        for auc in aucs:
            ln = plt.plot(auc['x'], auc['y'], label=auc['name'])
            if auc['color'] is not None:
                ln.set_color(auc['color'])
        plt.plot([0, 1], [0, 1], '--', color='grey')
        plt.ylabel('True Positive Rate')
        plt.xlabel('False positive rate')
        plt.legend()
        plt.show()

    @staticmethod
    def gen_point_plot_groups(df, grp_config, legend_texts, sep='\t', model='death'):
        model_df = df[df['outcome']==model]
        legend_data = []
        grps_list = []
        for gc in grp_config:
            idx = 0
            for f in gc['features']:
                grps = []
                xidx = 0
                for fg in gc['feature_grp']:
                    g = {"name": f}
                    g['ycentral'] = model_df[model_df['feature']==fg][f].iloc[0]
                    stdev = model_df[model_df['feature']==fg][f + '_stdev'].iloc[0]
                    g['ymin'] = g['ycentral'] - stdev
                    g['ymax'] = g['ycentral'] + stdev
                    g['x'] = gc['x_labels'][xidx]
                    g['color'] = gc['colors'][idx]
                    grps.append(g)
                    xidx += 1
                grps_list.append(grps)
                legend_data.append({'l': f, 'c': gc['colors'][idx]})
                idx += 1
        idx = 0
        for l in legend_data:
            l['l'] = legend_texts[idx]
            idx += 1
        return grps_list, legend_data

    @staticmethod
    def pointplot(grps_list, legends, xlabel, ylabel='feature coefficient', output_file=None):
        # grps = [
        #     {"name": "grp1", "ymin": 10, "ymax": 20, "ycentral": 15},
        #     {"name": "grp2", "ymin": 15, "ymax": 30, "ycentral": 26},
        #     {"name": "grp3", "ymin": 30, "ymax": 40, "ycentral": 33}
        # ]
        plt.figure()
        fig = plt.gcf()
        # offset = lambda p: transforms.ScaledTranslation(p/72.,0, plt.gcf().dpi_scale_trans)
        # trans = plt.gca().transData
        for grps in grps_list:
            idx = 0
            group_links_x = []
            group_links_y = []
            for g in grps:
                plt.plot([g['x'], g['x']], [g['ymin'], g['ymax']], '-', lw=2, color=g['color'])
                plt.scatter(g['x'], g['ycentral'], marker='o', color=g['color']) #, transform=trans+offset(-5 * idx))
                group_links_x.append(g['x'])
                group_links_y.append(g['ycentral'])
                idx += 1
            print(group_links_x, group_links_y)
            plt.plot(group_links_x, group_links_y, '-', color=grps[0]['color'])

        plt.plot([-.2, 2.5], [0, 0], '--', color='grey')
        y_start = -1
        y_step = .25
        idx = 0
        for l in legends:
            y = y_start - y_step * idx
            plt.plot([-0.2, 0], [y, y], '-', color=l['c'])
            plt.text(0.02, y - .05, l['l'])
            idx += 1
        plt.ylabel(ylabel)
        plt.xlabel(xlabel)
        plt.show()
        if output_file is not None:
            plt.draw()
            fig.savefig(output_file)
            print('{:s} saved'.format(output_file))

    @staticmethod
    def model_coef_table(config):
        model_perform_file = config['coef_file']
        model_turning_file = config['model_turning_file']
        mt_df = pd.read_csv(model_turning_file, sep='\t')
        df = pd.read_csv(model_perform_file, sep='\t')
        ms = config['model_selector']
        model_predictors_labels = config['model_predictors_labels']
        models = []
        mts = []
        for sel in ms:
            mask = df['outcome'].notna()
            mt_mask = mt_df['outcome'].notna()
            for k in sel:
                mask = mask & (df[k] == sel[k])
                mt_mask = mt_mask & (mt_df[k] == sel[k])
            models.append(df[mask])
            mts.append(mt_df[mt_mask])
        feature_groups = config['feature_groups']
        result = []
        for cat in feature_groups:
            c = cat['category']
            vars = cat['variables']
            cat_result = {'category': c, "data": []}
            result.append(cat_result)
            for v in vars:
                col = v['field']
                row = [v['label']]
                for r in models:
                    if not pd.isna(r[col].iloc[0]):
                        coef = r[col].iloc[0]
                        row.append('{:.04f} ({:.03f})'.format(coef, math.exp(coef)))
                    else:
                        row.append('--')
                cat_result['data'].append(row)
        meta = []
        idx = 0
        for mt in mts:
            model_predictors_labels[idx] = model_predictors_labels[idx] + \
                                           ' N: {:.0f}({:.01%})'.format(mt['cv_total'].iloc[0], mt['cv_P'].iloc[0]/mt['cv_total'].iloc[0])
            meta.append('{:.04f}'.format(mt['Intercept'].iloc[0]))
            idx += 1
        headers = ['Category', 'Predictor'] + model_predictors_labels
        print(result)
        print(VisGenerator.format_tab(headers, result))
        print('\t'.join(['Intercept', ''] + meta))
        return result

    @staticmethod
    def model_performance_tab(config):
        model_turning_file = config['model_turning_file']
        mt_df = pd.read_csv(model_turning_file, sep='\t')
        ms = config['model_selector']
        model_predictors_labels = config['model_predictors_labels']
        mts = []
        for sel in ms:
            mt_mask = mt_df['outcome'].notna()
            for k in sel:
                mt_mask = mt_mask & (mt_df[k] == sel[k])
            mts.append(mt_df[mt_mask])
        feature_groups = config['perfm_groups']
        result = []
        for cat in feature_groups:
            c = cat['category']
            vars = cat['variables']
            cat_result = {'category': c, "data": []}
            result.append(cat_result)
            for v in vars:
                col = v['field']
                row = [v['label']]
                for r in mts:
                    row.append('{:.04f}'.format(r[col].iloc[0]) if not pd.isna(r[col].iloc[0]) else '-')
                cat_result['data'].append(row)
        meta = []
        idx = 0
        for mt in mts:
            model_predictors_labels[idx] = model_predictors_labels[idx] + \
                                           ' N: {:.0f}({:.01%})'.format(mt['cv_total'].iloc[0], mt['cv_P'].iloc[0]/mt['cv_total'].iloc[0])
            # meta.append('{:.04f}'.format(mt['Intercept'].iloc[0]))
            idx += 1
        headers = ['Performance', 'Metrics'] + model_predictors_labels
        print(result)
        print(VisGenerator.format_tab(headers, result))
        # print('\t'.join(['Intercept', ''] + meta))
        return result


def load_json_data(file_path):
    data = None
    with codecs.open(file_path, encoding='utf-8') as rf:
        data = json.load(rf, encoding='utf-8')
    return data


def gen_predictor_point_plots(conf):
    data_file = conf['data_file']
    df = pd.read_csv(data_file, sep='\t')
    pgs = conf['predictor_groups']
    for plot_group in pgs:
        print('working on ' + plot_group['name'])
        models = plot_group['models']
        model_labels = plot_group['model_labels']
        idx = 0
        for m in models:
            grps, legends = VisGenerator.gen_point_plot_groups(
                df, grp_config=plot_group['group_config'], model=m, legend_texts=plot_group['legent_texts']
            )
            print(json.dumps(grps))
            VisGenerator.pointplot(grps, legends, xlabel='Predictor Groups for ' + model_labels[idx],
                                   output_file=join(conf['output_folder'], '{:s}_{:s}.png'.format(plot_group['name'], m)))
            idx += 1


if __name__ == "__main__":
    tab_confs = load_json_data('tab_configs.json')
    vg = VisGenerator(tab_confs['raw_data'])
    # - sankey diagram
    # vg.sankey_diagram('./sankey.png')

    # - descriptive tables
    # vg.descriptive_table(tab_confs['desc_tab'])
    vg.print_basic_stats()

    # - univariate tables
    # VisGenerator.univariate_table(tab_confs['univariate'],
    #                               tab_confs['univariate_files']['cat_file'],
    #                               tab_confs['univariate_files']['num_file'],
    #                               tab_confs['univariate_files']['cv_tuning_file'])

    # - auc figs
    # VisGenerator.prob_lifting_auc(tab_confs['validation_auc_b']['prob_lifting_files'],
    #                               tab_confs['validation_auc_b']['labels'])
    # - predictor groups point plots
    # gen_predictor_point_plots(tab_confs['predictors_point_plots'])
    # - model coefs
    # VisGenerator.model_coef_table(tab_confs['model_coefs'])
    # - model performances
    # VisGenerator.model_performance_tab(tab_confs['model_performances'])
