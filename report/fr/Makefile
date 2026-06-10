# ============================================================================
# CAIMP — Makefile (rapport français)
# Usage : make [all|clean|view|bib]
# ============================================================================

MAIN     := main
PDFVIEWER := xdg-open   # Linux ; remplacer par 'open' sur macOS
LATEXMK  := latexmk

.PHONY: all clean view bib

all:
	$(LATEXMK) -pdf -bibtex -interaction=nonstopmode $(MAIN).tex

bib:
	$(LATEXMK) -pdf -bibtex -g $(MAIN).tex

view: all
	$(PDFVIEWER) $(MAIN).pdf &

clean:
	$(LATEXMK) -C $(MAIN).tex
	rm -f *.aux *.bbl *.bcf *.blg *.lof *.log *.lot *.out \
	      *.run.xml *.toc *.fdb_latexmk *.fls *.synctex.gz
	find . -name "*.aux" -delete
