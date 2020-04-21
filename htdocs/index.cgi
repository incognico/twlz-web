#!/usr/bin/env perl

# Copyright 2016-2020 Nico R. Wohlgemuth

use utf8;
use strict;
use warnings;

use 5.16.0;
no warnings 'experimental::smartmatch';

use CGI qw(header param -utf8);
use CGI::Carp qw(fatalsToBrowser warningsToBrowser);
use DBI;
use Encode::Simple qw(encode_utf8_lax decode_utf8_lax);
use HTML::Entities;
use JSON;
use LWP::Simple '!head';
use POSIX 'ceil';
use SQL::Abstract::Limit;
use Template;
use Text::Truncate;

my $debug       = 0;
my $title       = 'twilightzone Sven Co-op Server';
my $db          = '/srv/www/twlz.lifeisabug.com/db/scstats.db';
my $steamapikey = '';
my $steamapiurl = 'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key='.$steamapikey.'&steamids=';
my $mapsapikey  = '';

my $ttvars = {
   mainurl        => 'https://twlz.lifeisabug.com',
   description    => 'twilightzone Sven Co-op Server',
   statsperpage   => 25,
   scorelimit     => 1500,
   datapointlimit => 720,
};

my %ttopts = (
   INCLUDE_PATH => '/srv/www/twlz.lifeisabug.com/templates/',
   PRE_CHOMP    => 2,
   POST_CHOMP   => 2,
);

croak("template folder $ttopts{INCLUDE_PATH} does not exist") unless (-e $ttopts{INCLUDE_PATH});

my $sql = SQL::Abstract::Limit->new(limit_dialect => 'LimitOffset');
my $tt  = Template->new(\%ttopts);

my $qpage       = param('page');
my $qdest       = param('dest');
my $qgeo        = param('geo');
my $qactiveonly = param('activeonly');

#$qdest = 'stats' unless ($qdest);
$qdest = 'info' unless ($qdest);
$qpage = 1 unless ($qpage && $qpage >= 1);

$$ttvars{dest}       = $qdest;
$$ttvars{activeonly} = $qactiveonly;

sub duration {
   my $sec = shift;

   return '?' unless ($sec);

   my @gmt = gmtime($sec);

   $gmt[5] -= 70;
   return   ($gmt[5] ?                                                       $gmt[5].'y' : '').
            ($gmt[7] ? ($gmt[5]                                  ? ' ' : '').$gmt[7].'d' : '').
            ($gmt[2] ? ($gmt[5] || $gmt[7]                       ? ' ' : '').$gmt[2].'h' : '').
            ($gmt[1] ? ($gmt[5] || $gmt[7] || $gmt[2]            ? ' ' : '').$gmt[1].'m' : '');
#            ($gmt[0] ? ($gmt[5] || $gmt[7] || $gmt[2] || $gmt[1] ? ' ' : '').$gmt[0].'s' : '');
}

sub pairwise_walk(&@) {
   my ($code, $prev) = (shift, shift);
   my @ret;

   push(@ret, $prev);

   for(@_) {
      push(@ret, $code->(local ($a, $b) = ($prev, $_)));
      $prev = $_;
   }

   return @ret;
}

sub printheader {
   if ($debug) {
      require Data::Dumper;
      Data::Dumper->import;
      $$ttvars{debug} = Dumper($ttvars);
   }

   print header(
      -charset => 'utf-8',
   );

   return;
}

my ($dbh, $stmt, @bind, $sth);

if ($qdest && $qdest eq 'colors') {
   $$ttvars{title}  = 'Glow & Trail Colors :: ' . $title;
   printheader();
   $tt->process('colors.tt', $ttvars) || croak($tt->error);
}
elsif ($qdest && $qdest eq 'heatmap') {
   $$ttvars{title} = 'Player Heatmap :: ' . $title;

   sqlite_connect();

   #my @where = (score => { '>', $$ttvars{scorelimit} });
   my @where = (datapoints => { '>', $$ttvars{datapointlimit} });

   ($stmt, @bind) = $sql->select('stats', 'lat, lon, joins', \@where, {});
   $sth = $dbh->prepare($stmt);
   $sth->execute(@bind);
   $$ttvars{latlon}     = $sth->fetchall_arrayref({});
   $$ttvars{mapsapikey} = $mapsapikey;
   $sth->finish;

   sqlite_disconnect();

   printheader();
   $tt->process('heatmap.tt', $ttvars) || croak($tt->error);
}
elsif ($qdest && $qdest eq 'furry') {
   printheader();
   $tt->process('furry.tt', $ttvars) || croak($tt->error);
}
#else {
#elsif (0) {
elsif ($qdest && $qdest eq 'stats') {
   my @where;

   if ($qactiveonly) {
      @where = (
         -and => [
            datapointgain => { '>', 0 },
            [
               -and => [ scoregain => { '!=', 0 } ],
               -or  => { deathgain => { '!=', 0 } }
            ]
         ]
      );
   }
   else {
      @where = (
         #score => { '>', $$ttvars{scorelimit}-1 }
         datapoints => { '>', $$ttvars{datapointlimit} }
      );
   }

   sqlite_connect();

   ($stmt, @bind) = $sql->select('stats', 'steamid64, name, CAST(score AS INTEGER) AS score, deaths, CAST(scoregain AS INTEGER) AS scoregain, deathgain, geo, datapoints, datapointgain, (CAST(score AS INTEGER) + datapoints) AS mix, (CAST(scoregain AS INTEGER) + datapointgain) AS mixgain', \@where, ($qactiveonly ? \'mixgain DESC' : \'mix DESC'), $$ttvars{statsperpage}, $qpage * $$ttvars{statsperpage} - $$ttvars{statsperpage});
   #($stmt, @bind) = $sql->select('stats', 'steamid64, name, CAST(score AS INTEGER) AS score, deaths, scoregain, deathgain, geo, datapoints, datapointgain', \@where, ($qactiveonly ? \'scoregain DESC, deathgain ASC' : \'score DESC, deaths ASC'), $$ttvars{statsperpage}, $qpage * $$ttvars{statsperpage} - $$ttvars{statsperpage});
   $sth = $dbh->prepare($stmt);
   $sth->execute(@bind);
   $$ttvars{sql} = $sth->fetchall_arrayref({});
   $sth->finish;

   ($stmt, @bind) = $sql->select('stats', 'COUNT(*) as cnt', \@where);
   $sth = $dbh->prepare($stmt);
   $sth->execute(@bind);
   my $statscnt = $sth->fetchall_arrayref({});
   $sth->finish;
   
   ($stmt, @bind) = $sql->select('stats', 'COUNT(*) as cnt', {});
   $sth = $dbh->prepare($stmt);
   $sth->execute(@bind);
   my $allstatscnt = $sth->fetchall_arrayref({});
   $sth->finish;

   sqlite_disconnect();

   $$ttvars{totalplayers}    = $statscnt->[0]->{cnt};
   $$ttvars{alltotalplayers} = $allstatscnt->[0]->{cnt};

   my @steamidlist;

   for (@{$$ttvars{sql}}) {
      $_->{trname}       = encode_entities(truncstr(decode_utf8_lax($_->{name}), 28, '..'));
      $_->{name}         = encode_entities(decode_utf8_lax($_->{name}));
      $_->{score}        = ceil($_->{score});
      $_->{scoregain}    = ceil($_->{scoregain});
      $_->{playtime}     = duration($_->{datapoints}*30);
      $_->{playtimegain} = $_->{datapointgain} ? duration($_->{datapointgain} % 2 ? ($_->{datapointgain}*30)+30 : $_->{datapointgain} * 30) : 0;
      push(@steamidlist, $_->{steamid64});
   }

   $$ttvars{pagecount} = ceil($$ttvars{totalplayers}/$$ttvars{statsperpage});

   my $pageplusminus = 1;
   my @pages         = (1..$pageplusminus, $qpage-$pageplusminus..$qpage+$pageplusminus, ($$ttvars{pagecount}+1)-$pageplusminus..$$ttvars{pagecount});
   @pages = sort{ $a <=> $b } keys %{{ map { $_ => 1 } @pages }};

   while ($pages[0] < 1) {
      shift(@pages);
   }

   while ($pages[-1] > $$ttvars{pagecount}) {
      pop(@pages);
   }

   @pages = pairwise_walk { $a+1 == $b ? $b : ('..', $b) } @pages;

   my $steamids;
   $steamids .= pop(@steamidlist) . ',' while (@steamidlist);

   my $content = get($steamapiurl . $steamids);
   croak "Couldn't query Steam API. Please refresh the page." unless (defined $content);
   my $result = decode_json($content);

   my %steamapi;
   @steamapi{map $_->{steamid}, @{$$result{response}{players}}} = @{$$result{response}{players}};
   $steamapi{$_}{personaname} = encode_entities($steamapi{$_}{personaname}) for (keys %steamapi);
   #$steamapi{$_}{avatar} = LWP::Simple::head($steamapi{$_}{avatar}) ? $steamapi{$_}{avatar} : 'https://steamcdn-a.akamaihd.net/steamcommunity/public/images/avatars/fe/fef49e7fa7e1997310d705b2a6158ff8dc1cdfeb.jpg' for (keys %steamapi);

   $$ttvars{steamapi} = \%steamapi;
   $$ttvars{title}    = 'Player Statistics :: ' . $title;
   $$ttvars{page}     = $qpage;
   $$ttvars{pages}    = \@pages;
   $$ttvars{dplim}    = duration($$ttvars{datapointlimit}*30);

   printheader();
   
   $tt->process('stats.tt', $ttvars) || croak($tt->error);
}
else {
   $$ttvars{title} = 'Info :: ' . $title;
   printheader();
   $tt->process('info.tt', $ttvars) || croak($tt->error);
}

sub sqlite_connect {
   unless ($dbh = DBI->connect("DBI:SQLite:dbname=$db", '', '', { AutoCommit => 1 })) {
      croak($DBI::errstr);
   }
   else {
      return 0;
   }
}

sub sqlite_disconnect {
   $dbh->disconnect;

   return;
}
