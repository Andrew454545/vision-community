# Verify the complete immutable public-source snapshot before Python executes.
use strict;
use warnings;
use Digest::SHA;
use JSON::PP qw(decode_json);
use File::Find;
use File::Basename qw(dirname);
use Fcntl qw(:mode);

sub mismatch { die "private_source_mismatch\n"; }
my ($root, $expected) = @ARGV;
@ARGV == 2 && $expected =~ /\A[a-f0-9]{64}\z/ && -d $root && !-l $root or mismatch();
my $manifest = "$root/source-inventory.json";
-f $manifest && !-l $manifest && -s $manifest <= 2 * 1024 * 1024 or mismatch();
open my $metadata, '<:raw', $manifest or mismatch();
my $raw; { local $/; $raw = <$metadata>; }
close $metadata;
Digest::SHA::sha256_hex($raw) eq $expected or mismatch();
my $pins = eval { decode_json($raw) }; $pins && ref($pins) eq 'HASH' or mismatch();
$pins->{version} == 1 && ref($pins->{files}) eq 'HASH' && keys(%{$pins->{files}}) <= 256 or mismatch();
my %dirs;
for my $name (keys %{$pins->{files}}) {
    $name =~ /\A(?:community|calibration|macos)\/[A-Za-z0-9_.+\/-]+\z/
        && $name !~ /(?:\A|\/)\.\.?(?:\/|\z)/ or mismatch();
    my $pin = $pins->{files}{$name}; ref($pin) eq 'HASH'
        && $pin->{sha256} =~ /\A[a-f0-9]{64}\z/
        && $pin->{bytes} =~ /\A[0-9]+\z/ && $pin->{bytes} <= 16 * 1024 * 1024 or mismatch();
    my $directory = dirname($name);
    while ($directory ne '.') { $dirs{$directory}=1; $directory=dirname($directory); }
}
my %seen;
my $entries=0;
find({ no_chdir=>1, follow=>0, wanted=>sub {
    my $path=$File::Find::name; return if $path eq $root;
    ++$entries <= 1024 or mismatch();
    my $name=substr($path,length($root)+1);
    my @info=lstat($path); @info && !S_ISLNK($info[2]) or mismatch();
    if (S_ISDIR($info[2])) { exists $dirs{$name} or mismatch(); }
    elsif (S_ISREG($info[2])) {
        if ($name eq 'source-inventory.json') { return; }
        my $pin=$pins->{files}{$name}; $pin && $info[7] == $pin->{bytes} or mismatch();
        open my $body,'<:raw',$path or mismatch();
        my $hash=Digest::SHA->new(256); $hash->addfile($body); close $body;
        $hash->hexdigest eq $pin->{sha256} or mismatch();
        my @after=lstat($path);
        @after && join(':',@info[0,1,2,7,9]) eq join(':',@after[0,1,2,7,9]) or mismatch();
        $seen{$name}=1;
    } else { mismatch(); }
}},$root);
for my $name (keys %{$pins->{files}}) { $seen{$name} or mismatch(); }
print "private_source_verified\n";
