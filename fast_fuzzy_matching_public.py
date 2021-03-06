# -*- coding: utf-8 -*-
"""Fast Fuzzy Matching public.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1qhBwDRitrgapNhyaHGxCW8uKK5SWJblW

#Fast Fuzzy Matching
This notebook shows how to use TD IDF to both dedupe and match records at scale
"""

import pandas as pd
pd.set_option('display.max_colwidth', -1)
from tqdm import tqdm
from google.colab import drive
import os
from matplotlib import style
style.use('fivethirtyeight')

"""The data can be found at the following link:
https://drive.google.com/file/d/1EAXvkiik5EO8FcpEwfX3muQEm6cqPGrQ/view?usp=sharing

"""

names =  pd.read_csv('messy org names.csv',encoding='latin')
print('The shape: %d x %d' % names.shape)
print('There are %d unique values' % names.buyer.shape[0])

"""##De duplication:"""

import re
!pip install ftfy # amazing text cleaning for decode issues..
from ftfy import fix_text

def ngrams(string, n=3):
    string = str(string)
    string = fix_text(string) # fix text
    string = string.encode("ascii", errors="ignore").decode() #remove non ascii chars
    string = string.lower()
    chars_to_remove = [")","(",".","|","[","]","{","}","'"]
    rx = '[' + re.escape(''.join(chars_to_remove)) + ']'
    string = re.sub(rx, '', string)
    string = string.replace('&', 'and')
    string = string.replace(',', ' ')
    string = string.replace('-', ' ')
    string = string.title() # normalise case - capital at start of each word
    string = re.sub(' +',' ',string).strip() # get rid of multiple spaces and replace with a single
    string = ' '+ string +' ' # pad names for ngrams...
    string = re.sub(r'[,-./]|\sBD',r'', string)
    ngrams = zip(*[string[i:] for i in range(n)])
    return [''.join(ngram) for ngram in ngrams]

print('All 3-grams in "Department":')
print(ngrams('Department'))

import numpy as np
from scipy.sparse import csr_matrix
!pip install sparse_dot_topn #uncomment to install
import sparse_dot_topn.sparse_dot_topn as ct


def awesome_cossim_top(A, B, ntop, lower_bound=0):
    # force A and B as a CSR matrix.
    # If they have already been CSR, there is no overhead
    A = A.tocsr()
    B = B.tocsr()
    M, _ = A.shape
    _, N = B.shape
 
    idx_dtype = np.int32
 
    nnz_max = M*ntop
 
    indptr = np.zeros(M+1, dtype=idx_dtype)
    indices = np.zeros(nnz_max, dtype=idx_dtype)
    data = np.zeros(nnz_max, dtype=A.dtype)

    ct.sparse_dot_topn(
        M, N, np.asarray(A.indptr, dtype=idx_dtype),
        np.asarray(A.indices, dtype=idx_dtype),
        A.data,
        np.asarray(B.indptr, dtype=idx_dtype),
        np.asarray(B.indices, dtype=idx_dtype),
        B.data,
        ntop,
        lower_bound,
        indptr, indices, data)

    return csr_matrix((data,indices,indptr),shape=(M,N))

from sklearn.feature_extraction.text import TfidfVectorizer

org_names = names['buyer'].unique()
vectorizer = TfidfVectorizer(min_df=1, analyzer=ngrams)
tf_idf_matrix = vectorizer.fit_transform(org_names)

import time
t1 = time.time()
matches = awesome_cossim_top(tf_idf_matrix, tf_idf_matrix.transpose(), 10, 0.85)
t = time.time()-t1
print("SELFTIMED:", t)

"""#### Comparison to traditional matching
This code prints the time it takes to compare <b>only one</b> item against the population. As you can see, the TD IDF approach can match all items (3,600) significantly faster than it takes to compare a single item using the fuzzywuzzy library.
"""

!pip install fuzzywuzzy
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

t1 = time.time()
print(process.extractOne('Ministry of Justice', org_names))
t = time.time()-t1
print("SELFTIMED:", t)
print("Estimated hours to complete for full dataset:", (t*len(org_names))/60/60)

"""#### Inputting results into a df:"""

def get_matches_df(sparse_matrix, name_vector, top=100):
    non_zeros = sparse_matrix.nonzero()
    
    sparserows = non_zeros[0]
    sparsecols = non_zeros[1]
    
    if top:
        nr_matches = top
    else:
        nr_matches = sparsecols.size
    
    left_side = np.empty([nr_matches], dtype=object)
    right_side = np.empty([nr_matches], dtype=object)
    similairity = np.zeros(nr_matches)
    
    for index in range(0, nr_matches):
        left_side[index] = name_vector[sparserows[index]]
        right_side[index] = name_vector[sparsecols[index]]
        similairity[index] = sparse_matrix.data[index]
    
    return pd.DataFrame({'left_side': left_side,
                          'right_side': right_side,
                           'similairity': similairity})

matches_df = get_matches_df(matches, org_names, top=1000)
matches_df = matches_df[matches_df['similairity'] < 0.99999] # Remove all exact matches
matches_df.sample(20)

matches_df.sort_values(['similairity'], ascending=False).head(20)

"""## Record linkage
Using a similar technique to the above, we can join our messy data to a clean set of master data.

The clean 'Gov Orgs ONS.xlsx' dataset can be found at the following link:
https://drive.google.com/file/d/1uBxlrASNMA215x4o4pu8JmtA2Iu-sLNn/view?usp=sharing
"""

##################
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
import re

clean_org_names = pd.read_excel('Gov Orgs ONS.xlsx')
clean_org_names = clean_org_names.iloc[:, 0:6]

org_name_clean = clean_org_names['Institutions'].unique()

print('Vecorizing the data - this could take a few minutes for large datasets...')
vectorizer = TfidfVectorizer(min_df=1, analyzer=ngrams, lowercase=False)
tfidf = vectorizer.fit_transform(org_name_clean)
print('Vecorizing completed...')

from sklearn.neighbors import NearestNeighbors
nbrs = NearestNeighbors(n_neighbors=1, n_jobs=-1).fit(tfidf)

org_column = 'buyer' #column to match against in the messy data
unique_org = set(names[org_column].values) # set used for increased performance


###matching query:
def getNearestN(query):
  queryTFIDF_ = vectorizer.transform(query)
  distances, indices = nbrs.kneighbors(queryTFIDF_)
  return distances, indices

import time
t1 = time.time()
print('getting nearest n...')
distances, indices = getNearestN(unique_org)
t = time.time()-t1
print("COMPLETED IN:", t)

unique_org = list(unique_org) #need to convert back to a list
print('finding matches...')
matches = []
for i,j in enumerate(indices):
  temp = [round(distances[i][0],2), clean_org_names.values[j][0][0],unique_org[i]]
  matches.append(temp)

print('Building data frame...')  
matches = pd.DataFrame(matches, columns=['Match confidence (lower is better)','Matched name','Origional name'])
print('Done')

matches.head(10)

