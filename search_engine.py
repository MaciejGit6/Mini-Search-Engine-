import requests
from bs4 import BeautifulSoup
import re
import math
import json
import os

import time
from urllib.parse import urljoin, urlparse
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Text Processing 

class TextProcessor:
    STOP_WORDS = set([
        "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", 
        "in", "on", "at", "to", "for", "with", "by", "about", "as", "of", "it", "this"
    ])


    @staticmethod
    def normalize(text):
        """Lowercase and extract words."""
        words = re.findall(r'\b[a-z0-9]+\b', text.lower())

        return [w for w in words if w not in TextProcessor.STOP_WORDS]




# Multithreaded Crawler

class Crawler:
    def __init__(self, max_depth=2, max_pages=50, delay=0.5):
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.delay = delay

        self.visited = set()
        self.documents = {} 
        self.lock = threading.Lock()

    def is_valid_url(self, url):
        parsed = urlparse(url)
        return bool(parsed.netloc) and bool(parsed.scheme) and parsed.scheme in ['http', 'https']

    def fetch_page(self, url):
        try:

            time.sleep(self.delay) 
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                return response.text
        except requests.RequestException:
            pass

        return None

    def crawl(self, seed_urls):
        print(f"Starting crawl with {len(seed_urls)} seed URLs...")
        queue = [(url, 0) for url in seed_urls if self.is_valid_url(url)]
        
        with ThreadPoolExecutor(max_workers=5) as executor:

            while queue and len(self.visited) < self.max_pages:

                current_batch = []
                while queue and len(current_batch) < 10:
                    current_batch.append(queue.pop(0))

                futures = {executor.submit(self.fetch_page, url): (url, depth) 
                           for url, depth in current_batch if url not in self.visited}

                for future in as_completed(futures):
                    url, depth = futures[future]
                    
                    with self.lock:
                        if url in self.visited or len(self.visited) >= self.max_pages:
                            continue
                        self.visited.add(url)

                    html = future.result()
                    if not html:
                        continue

                    soup = BeautifulSoup(html, 'html.parser')
                    text = soup.get_text(separator=' ', strip=True)
                    title = soup.title.string if soup.title else url

                    with self.lock:
                        self.documents[url] = {'text': text, 'title': title}

                    print(f"Crawled: {url} (Depth: {depth})")

                    if depth < self.max_depth:
                        for link in soup.find_all('a', href=True):
                            next_url = urljoin(url, link['href'])

                            next_url = next_url.split('#')[0] 
                            if self.is_valid_url(next_url) and next_url not in self.visited:
                                queue.append((next_url, depth + 1))
        
        return self.documents

# idx Engine

class Indexer:
    def __init__(self):
        
        self.inverted_index = defaultdict(lambda: defaultdict(int))
        self.doc_lengths = {} 

    def build_index(self, documents):
        print("Building index...")
        for url, doc_data in documents.items():
            words = TextProcessor.normalize(doc_data['text'])
            self.doc_lengths[url] = len(words)
            
            word_counts = Counter(words)
            for word, count in word_counts.items():
                self.inverted_index[word][url] = count
        print(f"Index built with {len(self.inverted_index)} unique terms.")



class Ranker:
    def __init__(self, indexer):

        self.index = indexer.inverted_index
        self.doc_lengths = indexer.doc_lengths

        self.total_docs = len(indexer.doc_lengths)

    def calculate_tf_idf(self, query_terms, operator="OR"):
        scores = defaultdict(float)
        doc_sets = []

        
        for term in query_terms:
            if term in self.index:
                doc_sets.append(set(self.index[term].keys()))
            else:
                doc_sets.append(set())

        if not doc_sets:
            return {}

        
        if operator == "AND":
            valid_docs = set.intersection(*doc_sets) if doc_sets else set()
        else:
            valid_docs = set.union(*doc_sets) if doc_sets else set()

        for term in query_terms:
            if term not in self.index:
                continue
            
            df = len(self.index[term])
            idf = math.log10(self.total_docs / (1 + df))

            for url, term_count in self.index[term].items():
                if url in valid_docs:
                    
                    tf = term_count / self.doc_lengths[url]
                    scores[url] += tf * idf

       
        return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))



class Storage:
    def __init__(self, filepath="search_index.json"):
        self.filepath = filepath

    def save(self, indexer, documents):
        data = {
            'index': {k: dict(v) for k, v in indexer.inverted_index.items()},
            'doc_lengths': indexer.doc_lengths,
            'documents': documents
        }
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print(f"Index saved to {self.filepath}")



    def load(self, indexer, crawler):
        if not os.path.exists(self.filepath):
            return False
        with open(self.filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        indexer.inverted_index = defaultdict(lambda: defaultdict(int), data['index'])
        indexer.doc_lengths = data['doc_lengths']
        crawler.documents = data['documents']
        print(f"Index loaded from {self.filepath}")
        return True



class SearchEngine:

    def __init__(self):
        self.crawler = Crawler(max_depth=1, max_pages=15)
        self.indexer = Indexer()
        self.storage = Storage()
    
    def generate_snippet(self, text, query_terms):
        words = text.split()
        normalized_words = [w.lower() for w in words]
        
        for i, word in enumerate(normalized_words):
            if any(term in word for term in query_terms):
                start = max(0, i - 10)
                end = min(len(words), i + 10)
                return "..." + " ".join(words[start:end]) + "..."
        return " ".join(words[:20]) + "..."

        

    def start(self):
        print("=== Mini Search Engine ===")
        if not self.storage.load(self.indexer, self.crawler):
            seed = input("No existing index found. Enter a seed URL to crawl: ").strip()

            docs = self.crawler.crawl([seed])
            self.indexer.build_index(docs)
            self.storage.save(self.indexer, docs)
            
        self.ranker = Ranker(self.indexer)
        self.cli_loop()

    def cli_loop(self):

        while True:

            print("\n" + "-"*40)
            query = input("Enter search query (or 'exit'): ").strip()
            if query.lower() == 'exit':
                break
            if not query:
                continue

            
            operator = "OR"
            if " AND " in query:
                operator = "AND"
                raw_terms = query.split(" AND ")
            elif " OR " in query:
                operator = "OR"
                raw_terms = query.split(" OR ")
            else:
                raw_terms = query.split()

            query_terms = TextProcessor.normalize(" ".join(raw_terms))
            
            if not query_terms:
                print("Query consists only of stop words. Try again.")
                continue

            start_time = time.time()
            results = self.ranker.calculate_tf_idf(query_terms, operator)
            elapsed = (time.time() - start_time) * 1000

            print(f"\nFound {len(results)} results in {elapsed:.2f}ms (Operator: {operator})")
            
            for i, (url, score) in enumerate(results.items(), 1):
                doc = self.crawler.documents[url]
                snippet = self.generate_snippet(doc['text'], query_terms)

                print(f"{i}. {doc['title']} (Score: {score:.4f})")
                print(f"   URL: {url}")
                print(f"   Snippet: {snippet}\n")

if __name__ == "__main__":
    engine = SearchEngine()
    engine.start()