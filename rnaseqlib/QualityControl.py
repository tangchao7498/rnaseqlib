import os
import sys
import time

import logging

import csv

import rnaseqlib
import rnaseqlib.fastx_utils as fastx_utils
import rnaseqlib.mapping.bedtools_utils as bedtools_utils
import rnaseqlib.utils as utils

import pandas
import pysam

from collections import defaultdict


class QualityControl:
    """ 
    Quality control object. Defined for
    RNA-Seq sample.
    """
    def __init__(self, sample, pipeline):
        # Pipeline instance that the sample is attached to
        self.pipeline = pipeline
        self.sample = sample
        self.settings_info = pipeline.settings_info
        # Define logger
        self.logger = utils.get_logger("QualityControl.%s" %(sample.label),
                                       self.pipeline.pipeline_outdirs["logs"])
        # QC header: order of QC fields to be outputted
        self.regions_header = ["num_ribo",
                               "num_exons",
                               "num_cds",
                               "num_introns",
                               "num_3p_utr",
                               "num_5p_utr",
                               "num_tRNAs"]
        self.qc_stats_header = ["percent_mapped",
                                "percent_unique",
                                "percent_ribo",
                                "percent_exons",
                                "percent_cds",     
                                "percent_introns",
                                "percent_3p_utr",
                                "percent_5p_utr",
                                "percent_tRNAs",
                                "3p_to_cds",
                                "5p_to_cds",
                                "3p_to_5p"]
        self.qc_header = ["num_reads", 
                          "num_mapped",
                          "num_unique_mapped"] + \
                          self.qc_stats_header + \
                          self.regions_header
        # QC results
        self.na_val = "NA"
        self.qc_results = defaultdict(lambda: self.na_val)
        # QC output dir
        self.qc_outdir = self.pipeline.pipeline_outdirs["qc"]
        # QC filename for this sample
        self.sample_outdir = os.path.join(self.qc_outdir,
                                          self.sample.label)
        utils.make_dir(self.sample_outdir)
        # Regions output dir
        self.regions_outdir = os.path.join(self.sample_outdir, "regions")
        utils.make_dir(self.regions_outdir)
        self.qc_filename = os.path.join(self.sample_outdir,
                                        "%s.qc.txt" %(self.sample.label))
        self.qc_loaded = False
        # use ensGene gene table for QC computations
        self.gene_table = self.pipeline.rna_base.gene_tables["ensGene"]
        # Load QC information if file corresponding to sample already exists
        self.load_qc_from_file()


    def load_qc_from_file(self):
        """
        Load QC data from file if already present.
        """
        self.logger.info("Attempting to load QC from file...")
        if os.path.isfile(self.qc_filename):
            self.logger.info("Loaded: %s" %(self.qc_filename))
            qc_in = csv.DictReader(open(self.qc_filename, "r"),
                                   delimiter="\t")
            # Load existing header
            self.qc_header = qc_in.fieldnames
            # Load QC field values
            self.qc_results = qc_in.next()
            self.qc_loaded = True
            

    def get_num_reads(self):
        """
        Return number of reads in FASTA/FASTQ file.

        For single-end samples, returns a single number.

        For paired-end samples, return a comma-separated
        pair of numbers: 'num_left_mate,num_right_mate'
        """
        self.logger.info("Getting number of reads.")
        if self.sample.paired:
            self.logger.info("Getting number of paired-end reads.")
            # Paired-end
            mate_reads = []
            for mate_rawdata in self.sample.rawdata:
                num_reads = 0
                fastx_entries = \
                    fastx_utils.get_fastx_entries(mate_rawdata.reads_filename)
                for entry in fastx_entries:
                    num_reads += 1
                mate_reads.append(num_reads)
            pair_num_reads = ",".join(map(str, mate_reads))
            return pair_num_reads
        else:
            self.logger.info("Getting number of single-end reads.")
            num_reads = 0
            # Single-end
            fastx_entries = \
                fastx_utils.get_fastx_entries(self.sample.rawdata.reads_filename)
            for entry in fastx_entries:
                num_reads += 1
            return num_reads

            
    def get_num_mapped(self):
        """
        Get number of mapped reads, not counting duplicates, i.e.
        reads that have alignments in the BAM file.
        """
        self.logger.info("Getting number of mapped reads.")        
        num_mapped = count_nondup_reads(self.sample.bam_filename)
        return num_mapped


    def get_num_unique_mapped(self):
        self.logger.info("Getting number of unique reads.")
        num_unique_mapped = \
            count_nondup_reads(self.sample.unique_bam_filename)
        self.logger.info("Num uniq mapped: %d" %(num_unique_mapped))
        return num_unique_mapped
    

    def get_exon_intergenic_ratio(self):
        self.logger.info("Getting exon intergenic ratio.")
        return 0
    

    def get_exon_intron_ratio(self):
        pass

    
    def get_num_ribo(self, chr_ribo="chrRibo"):
        """
        Compute the number of ribosomal mapping reads per
        sample.

        - chr_ribo denotes the name of the ribosome containing
          chromosome.
        """
        self.logger.info("Getting number of ribosomal reads..")
        bamfile = pysam.Samfile(self.sample.bam_filename, "rb")
        # Retrieve all reads on the ribo chromosome
        ribo_reads = bamfile.fetch(reference=chr_ribo,
                                   start=None,
                                   end=None)
        # Count reads (fetch returns an iterator)
        # Do not count duplicates
        num_ribo = count_nondup_reads(ribo_reads)
        return num_ribo


    def get_qc(self):
        return self.qc_results
    

    def get_num_exons(self):
        """
        Return number of reads mapping to exons.
        """
        self.logger.info("Getting number of exonic reads..")
        merged_exons_filename = os.path.join(self.gene_table.exons_dir,
                                             "ensGene.merged_exons.bed")
        output_basename = "region.merged_exons.bed"
        merged_exons_map_fname = os.path.join(self.regions_outdir,
                                              output_basename)
        num_exons_reads = 0
        result = \
            bedtools_utils.count_reads_matching_intervals(self.sample.ribosub_bam_filename,
                                                          merged_exons_filename,
                                                          merged_exons_map_fname,
                                                          self.logger)
        if result is None:
            self.logger.warning("Mapping to exons failed.")
        else:
            self.logger.info("Found bedtools output file for exons.")
            num_exons_reads = result
        return num_exons_reads

    
    def get_num_introns(self):
        """
        Return number of reads mapping to introns.
        """
        self.logger.info("Getting number of intronic reads..")
        introns_filename = os.path.join(self.gene_table.introns_dir,
                                        "ensGene.introns.bed")
        self.logger.info("Reading: %s" %(introns_filename))
        output_basename = "region.introns.bed"
        introns_map_fname = os.path.join(self.regions_outdir,
                                         output_basename)
        num_introns_reads = 0
        result = \
            bedtools_utils.count_reads_matching_intervals(self.sample.ribosub_bam_filename,
                                                          introns_filename,
                                                          introns_map_fname,
                                                          self.logger)
        if result is None:
            self.logger.warning("Mapping to introns failed.")
            return num_introns_reads
        else:
            self.logger.info("Found bedtools output file for introns.")
            num_introns_reads = result
        return num_introns_reads 


    def get_region_files(self):
        """
        Get region filenames to map reads to for QC and their
        labels.
        """
        # Merged exons 
        merged_exons_filename = os.path.join(self.gene_table.exons_dir,
                                             "ensGene.merged_exons.bed")
        # Introns 
        introns_filename = os.path.join(self.gene_table.introns_dir,
                                        "ensGene.introns.bed")
        # CDS-only merged exons
        merged_cds_only_exons_filename \
            = os.path.join(self.gene_table.exons_dir,
                           "ensGene.cds_only.merged_exons.bed")
        # 3' UTRs
        three_prime_utrs_fname = os.path.join(self.gene_table.utrs_dir,
                                              "ensGene.3p_utrs.bed")
        # 5' UTRs
        five_prime_utrs_fname = os.path.join(self.gene_table.utrs_dir,
                                             "ensGene.5p_utrs.bed")
        # tRNAs
        tRNAs_fname = os.path.join(self.gene_table.tRNAs_dir,
                                   "tRNAs.bed")
        region_files = [[merged_exons_filename,
                         "merged_exons"],
                        [introns_filename,
                         "introns"],
                        [merged_cds_only_exons_filename,
                         "cds_only.merged_exons"],
                        [three_prime_utrs_fname,
                         "3p_utrs"],
                        [five_prime_utrs_fname,
                         "5p_utrs"],
                        [tRNAs_fname,
                         "tRNAs"]]
        return [r[0] for r in region_files], [r[1] for r in region_files]

    
    def compute_regions(self):
        """
        Compute number of reads mapping to various regions.

        Mapping done based on uniquely mapped BAM reads.
        """
        self.logger.info("Computing reads in regions..")
        # Map reads to all regions
        regions_info = self.get_region_files()
        region_filenames, region_labels = regions_info
        # Check that all files exist
        for fname in region_filenames:
            if not os.path.isfile(fname):
                self.logger.critical("Cannot find regions filename for %s" \
                                     %(fname))
                sys.exit(1)
        self.qc_regions_bam = \
            os.path.join(self.regions_outdir, "qc_regions.bam")
        if not os.path.isfile(self.qc_regions_bam):
            num_regions = len(region_filenames)
            self.logger.info("Mapping reads to %d region types." \
                             %(num_regions))
            # Compute which reads map to each region
            region_results = \
                bedtools_utils.multi_tagBam(self.sample.unique_bam_filename,
                                            region_filenames,
                                            region_labels,
                                            self.qc_regions_bam,
                                            self.logger)
            if region_results is None:
                self.logger.critical("Mapping of reads to QC regions failed.")
                sys.exit(1)
        else:
            self.logger.info("QC regions BAM %s found, skipping.." \
                             %(self.qc_regions_bam))
        region_counts = \
            self.count_reads_in_qc_regions(self.qc_regions_bam)
        self.logger.info("Done counting reads in QC regions.")


    def count_reads_in_qc_regions(self, qc_regions_bam):
        """
        Count reads mapping to various QC regions in the
        BAM produced by tagBam.
        """
        if not os.path.isfile(qc_regions_bam):
            self.logger.critical("Cannot found reads, BAM file %s not found." \
                                 %(qc_regions_bam))
            return
        # Count reads in exons
        bam_file = pysam.Samfile(qc_regions_bam, "rb")
        self.logger.info("Counting reads in: %s" %(qc_regions_bam))
        region_counts = defaultdict(int)
        for bam_read in bam_file:
            # Read aligns to region of interest
            regions_field = None
            try:
                regions_field = bam_read.opt("YB")
            except KeyError:
                continue
            regions_detected = \
                map(lambda x: x.split(":")[0],
                    filter(lambda x: ":" in x, regions_field.split(";")))
            ##
            ## Rules for counting regions
            ##
            if "tRNA" in regions_detected:
                # If it maps to tRNAs, count it and discard
                # all other possible mapping for the read
                region_counts["tRNAs"] += 1
                continue
            if "merged_exons" in regions_detected:
                # If it's in an intron and an exon, discard it
                if "introns" in regions_detected:
                    continue
                # Count the exonic type: if it's an exon then
                # record it as either CDS, 3' UTR, or 5' UTR.
                # Note that these categories are mutually exclusive here
                if "cds_only.merged_exons" in regions_detected:
                    region_counts["num_cds"] += 1
                elif "3p_utrs" in regions_detected:
                    region_counts["num_3p_utr"] += 1
                elif "5p_utrs" in regions_detected:
                    region_counts["num_5p_utr"] += 1
                else:
                    # Misc exons: not 3p_UTR, not 5p_UTR and not
                    # CDS exons
                    region_counts["num_other_exons"] += 1
            elif ("cds_only.merged_exons" in regions_detected) and \
                 (len(regions_detected) == 1):
                # If the exon maps only to the CDS region, count it
                # as CDS
                region_counts["num_cds"] += 1
            elif ("introns" in regions_detected) and \
                 (len(regions_detected) == 1):
                # It maps to an intron and only an intron, so count it
                # as intronic read
                region_counts["num_introns"] += 1
        self.qc_results["num_cds"] = region_counts["num_cds"]
        self.qc_results["num_introns"] = region_counts["num_introns"]
        self.qc_results["num_3p_utr"] = region_counts["num_3p_utr"]
        self.qc_results["num_5p_utr"] = region_counts["num_5p_utr"]
        self.qc_results["num_tRNAs"] = region_counts["num_tRNAs"]
        # Number of exonic reads is defined as
        # sum of reads that fall in:
        #  - CDS exons
        #  - 3'/5' UTRs
        #  - Other misc. exons
        self.qc_results["num_exons"] = \
            region_counts["num_cds"] + \
            region_counts["num_other_exons"] + \
            region_counts["num_3p_utr"] + \
            region_counts["num_5p_utr"]
        # Collect sum of all the QC regions
        self.qc_results["qc_regions_total"] = \
            self.qc_results["num_exons"] + self.qc_results["num_introns"]
        

    def compute_basic_qc(self):
        """
        Compute basic QC stats like number of reads mapped.
        """
        self.qc_results["num_reads"] = self.get_num_reads()
        self.qc_results["num_mapped"] = self.get_num_mapped()
        self.qc_results["num_unique_mapped"] = self.get_num_unique_mapped()


    def get_percent_mapped(self):
        """
        Get percent of reads that were mapped.
        """
        percent_mapped = 0
        if self.qc_results["num_mapped"] == self.na_val:
            return percent_mapped
        if self.sample.paired:
            # For paired-end samples, divide the number of mapped
            # reads by the smaller of the two numbers of left mate
            # and right mates
            pair_denom = min(map(int,
                                 self.qc_results["num_reads"].split(",")))
            percent_mapped = \
                self.qc_results["num_mapped"] / float(pair_denom)
        else:
            percent_mapped = \
                self.qc_results["num_mapped"] / float(self.qc_results["num_reads"])
        percent_mapped *= float(100)
        return percent_mapped


    def get_percent_unique(self):
        """
        Get percent uniquely mapped.
        """
        percent_unique = 0
        self.logger.info("GET PERCENT UNIQUE: %d" %(self.qc_results["num_unique_mapped"]))
        if self.qc_results["num_unique_mapped"] == self.na_val:
            return percent_mapped
        if self.sample.paired:
            # For paired-end samples, divide the number of mapped
            # reads by the smaller of the two numbers of left mate
            # and right mates
            pair_denom = min(map(int,
                                 self.qc_results["num_reads"].split(",")))
            percent_unique = \
                self.qc_results["num_unique_mapped"] / float(pair_denom)
        else:
            percent_unique = \
                self.qc_results["num_unique_mapped"] / float(self.qc_results["num_mapped"])
        percent_unique *= float(100)
        return percent_unique

    
    def get_percent_ribo(self):
        """
        Get percent ribosomal RNA mapping reads.
        """
        percent_ribo = 0
        if self.qc_results["num_ribo"] == self.na_val:
            return percent_ribo
        percent_ribo = \
            self.qc_results["num_ribo"] / float(self.qc_results["num_unique_mapped"])
        return 0

    
    def get_percent_exons(self):
        """
        Get percent of reads in exons.
        """
        percent_exons = 0
        if self.qc_results["num_exons"] == self.na_val:
            return percent_exons
        percent_exons = \
            self.qc_results["num_exons"] / float(self.qc_results["qc_regions_total"])
        percent_exons *= float(100)
        return percent_exons


    def get_percent_introns(self):
        """
        Get percent of reads in introns.
        """
        percent_introns = 0
        if self.qc_results["num_introns"] == self.na_val:
            return percent_introns
        percent_introns = \
            self.qc_results["num_introns"] / float(self.qc_results["qc_regions_total"])
        percent_introns *= float(100)
        return percent_introns


    def get_percent_cds(self):
        """
        Get percent of reads in CDS.
        """
        percent_cds = 0
        if self.qc_results["num_cds"] == self.na_val:
            return percent_cds
        percent_cds = \
            self.qc_results["num_cds"] / float(self.qc_results["num_exons"])
        percent_cds *= float(100)
        return percent_cds


    def get_percent_3p_utr(self):
        """
        Get percent of exonic reads in 3' UTRs.
        """
        percent_3p_utr = 0
        if self.qc_results["num_3p_utr"] == self.na_val:
            return percent_3p_utr
        percent_3p_utr = \
            self.qc_results["num_3p_utr"] / float(self.qc_results["num_exons"])
        percent_3p_utr *= float(100)
        return percent_3p_utr


    def get_percent_5p_utr(self):
        """
        Get percent of exonic reads in 5' UTRs.
        """
        percent_5p_utr = 0
        if self.qc_results["num_5p_utr"] == self.na_val:
            return percent_5p_utr
        percent_5p_utr = \
            self.qc_results["num_5p_utr"] / float(self.qc_results["num_exons"])
        percent_5p_utr *= float(100)
        return percent_5p_utr


    def get_percent_tRNAs(self):
        """
        Get percent tRNAs.
        """
        percent_tRNAs = 0
        if self.qc_results["num_tRNAs"] == self.na_val:
            return percent_tRNAs
        percent_tRNAs = \
            self.qc_results["num_tRNAs"] / float(self.qc_results["num_unique_mapped"])
        percent_tRNAs *= float(100)
        return percent_tRNAs


    def get_3p_to_cds(self):
        """
        Get 3' UTR to CDS ratio.
        """
        three_prime_to_cds = 0
        if (self.qc_results["percent_3p_utr"] == self.na_val) or \
           (self.qc_results["percent_cds"] == self.na_val):
            return three_prime_to_cds
        three_prime_to_cds = \
            self.qc_results["percent_3p_utr"] / float(self.qc_results["percent_cds"])
        return three_prime_to_cds


    def get_5p_to_cds(self):
        """
        Get 5' UTR to CDS ratio.
        """
        five_prime_to_cds = 0
        if (self.qc_results["percent_5p_utr"] == self.na_val) or \
           (self.qc_results["percent_cds"] == self.na_val):
            return five_prime_to_cds
        five_prime_to_cds = \
            self.qc_results["percent_5p_utr"] / float(self.qc_results["percent_cds"])
        return five_prime_to_cds


    def get_3p_to_5p(self):
        """
        Get 3' UTR to 5' UTR ratio.
        """
        three_to_five_prime = 0
        if (self.qc_results["percent_3p_utr"] == self.na_val) or \
           (self.qc_results["percent_5p_utr"] == self.na_val):
            return three_to_five_prime
        three_to_five_prime = \
            self.qc_results["percent_3p_utr"] / float(self.qc_results["percent_5p_utr"])
        return three_to_five_prime
    

    def compute_qc_stats(self):
        """
        Compute various statistics from the QC numbers we have.
        """
        # Check that the number of reads mapped is non-zero
        if (self.qc_results["num_mapped"] == self.na_val) or \
           (self.qc_results["num_mapped"] == 0):
            self.logger.critical("Cannot compute QC stats since number of reads "
                                 "mapped is not available!")
            self.logger.critical("num_mapped = %s" \
                                 %(str(self.qc_results["num_mapped"])))
            sys.exit(1)
        self.qc_stat_funcs = [("percent_unique", self.get_percent_unique),
                              ("percent_mapped", self.get_percent_mapped),
                              ("percent_ribo", self.get_percent_ribo),
                              ("percent_exons", self.get_percent_exons),
                              ("percent_introns", self.get_percent_introns),
                              ("percent_cds", self.get_percent_cds),
                              ("percent_3p_utr", self.get_percent_3p_utr),
                              ("percent_5p_utr", self.get_percent_5p_utr),
                              ("percent_tRNAs", self.get_percent_tRNAs),
                              ("3p_to_cds", self.get_3p_to_cds),
                              ("5p_to_cds", self.get_5p_to_cds),
                              ("3p_to_5p", self.get_3p_to_5p)]
        for stat_name, stat_func in self.qc_stat_funcs:
            self.qc_results[stat_name] = stat_func()
        

    def compute_qc(self):
        """
        Compute all QC metrics for sample.
        """
        self.logger.info("Computing QC for sample: %s" %(self.sample.label))
        # BAM-related statistics
        # First check that BAM file is present
        if (self.sample.bam_filename is None) or \
           (not os.path.isfile(self.sample.bam_filename)):
            print "WARNING: Cannot find BAM filename for %s" %(self.sample.label)
        else:
            # Basic QC stats
            self.compute_basic_qc()
            # Number of reads in various regions
            self.compute_regions()
            # Compute statistics from these results
            self.compute_qc_stats()
        # Set that QC results were loaded
        self.qc_loaded = True
        return self.qc_results
        
        
    def output_qc(self):
        """
        Output QC metrics for sample.
        """
        if os.path.isfile(self.qc_filename):
            print "SKIPPING %s, since %s already exists..." %(self.sample.label,
                                                              self.qc_filename)
            return None
        # Header for QC output file for sample
        qc_df = pandas.DataFrame([self.qc_results])
        # Write QC information as csv
        qc_df.to_csv(self.qc_filename,
                     cols=self.qc_header,
                     na_rep=self.na_val,
                     float_format="%.3f",
                     sep="\t",
                     index=False)
        

    def get_seq_cycle_profile(self, fastq_filename,
                              first_n_seqs=None):#sample):
        """
        Compute the average 'N' bases (unable to sequence)
        as a function of the position of the read.
        """
        fastq_entries = fastx_utils.get_read_fastx(fastq_filename)
        # Mapping from position in read to number of Ns
        num_n_bases = defaultdict(int)
        # Mapping from position in read to total number of
        # reads in that position
        num_reads = defaultdict(int)
        num_entries = 0
        print "Computing sequence cycle profile for: %s" %(fastq_filename)
        if first_n_seqs != None:
            print "Looking at first %d sequences only" %(first_n_seqs)
        for entry in fastq_entries:
            if first_n_seqs != None:
                # Stop at requested number of entries if asked to
                if num_entries >= first_n_seqs:
                    break
            header1, seq, header2, qual = entry
            seq_len = len(seq)
            for n in range(seq_len):
                if seq[n] == "N":
                    # Record occurrences of N
                    num_n_bases[n] += 1
                num_reads[n] += 1
            num_entries += 1
        # Compute percentage of N along each position
        percent_n = []
        for base_pos in range(max(num_reads.keys())):
            curr_percent_n = float(num_n_bases[base_pos]) / num_reads[base_pos]
            percent_n.append(curr_percent_n)
        return percent_n

        
class QCStats:
    """
    Represntation of QC stats for a set of samples.
    """
    def __init__(self, samples, qc_header, qc_objects,
                 sample_header="sample"):
        self.samples = samples
        self.sample_header = sample_header
        self.qc_objects = qc_objects
        self.qc_stats = None
        self.qc_header = qc_header
        self.na_val = "NA"


    def output_qc(self, output_filename):
        """
        Output QC to file.
        """
        print "Outputting QC information for all samples..."
        self.compile_qc(self.samples)
        self.to_csv(output_filename)


    def compile_qc(self):
        """
        Combined the QC output of a given set of samples
        into one object.
        """
        if len(self.samples) == 0:
            print "Error: No samples given to compile QC from!"
            sys.exit(1)
        qc_entries = []
        for sample in self.samples:
            # Copy sample's QC results
            sample_qc_results = self.qc_objects[sample.label].qc_results
            qc_entry = sample_qc_results.copy()
            # Record sample name
            qc_entry[self.sample_header] = sample.label
            qc_entries.append(qc_entry)
        self.qc_stats = pandas.DataFrame(qc_entries)
        return self.qc_stats
    

    def to_csv(self, output_filename):
        # Fetch QC header of first sample. Add to its
        # beginning a field for the sample name
        output_header = [self.sample_header] + self.qc_header
        for col in output_header:
            if col not in self.qc_stats.columns:
                print "WARNING: Could not find column %s in QC stats. " \
                      "Something probably went wrong in a previous " \
                      "step. Were your BAMs created successfully?" \
                      %(col)
        self.qc_stats.to_csv(output_filename,
                             sep="\t",
                             na_rep=self.na_val,
                             float_format="%.3f",
                             index=False,
                             cols=output_header)

##
## Misc. QC functions
##
def count_nondup_reads(bam_in):
    """
    Return number of BAM reads that appear in the file, excluding
    duplicates (i.e. only count unique read ids/QNAMEs.)

    Takes a filename or a stream.
    """
    bam_reads = bam_in
    if isinstance(bam_in, basestring):
        # We're passed a filename
        if not os.path.isfile(bam_in):
            print "WARNING: Could not find BAM file %s" %(bam_in)
            return 0
        else:
            bam_reads = pysam.Samfile(bam_in, "rb")
    bam_reads_ids = {}
    for read in bam_reads:
        bam_reads_ids[read.qname] = True
    num_reads = len(bam_reads_ids.keys())
    return num_reads
