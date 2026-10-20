using System.Security.Cryptography;
using System.Text;
using Mutagen.Bethesda;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Binary.Parameters;
using Mutagen.Bethesda.Plugins.Binary.Streams;
using Mutagen.Bethesda.Skyrim;
using Mutagen.Bethesda.Strings;

// Генератор узкого override средствами Mutagen. Исходная сборка только читается.
const string expectedHash = "a5b03f58aeefeb806f7c4e44981d4f3ba0bc125419d488d3fcc7a896768d3401";
const string patchName = "RFAB-ShockNova-NeutralTargets.esp";
const string effectEditorId = "WB_D100_FingersOfTheMountainNew_Effect_LightningStrike";

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: ShockNovaPatcher <source RFAB.esp> <output ESP>");
    return 2;
}

try
{
    var input = Path.GetFullPath(args[0]);
    var output = Path.GetFullPath(args[1]);
    if (!Path.GetFileName(input).Equals("RFAB.esp", StringComparison.OrdinalIgnoreCase)
        || !Path.GetFileName(output).Equals(patchName, StringComparison.Ordinal))
        throw new InvalidOperationException("Unexpected source or output filename.");
    if (File.Exists(output))
        throw new InvalidOperationException("Output already exists. Use a fresh build directory.");
    var originalHash = Hash(input);
    if (originalHash != expectedHash)
        throw new InvalidOperationException($"RFAB.esp differs from the researched base. Expected {expectedHash}; got {originalHash}. Recheck the records before rebuilding.");

    var utf8 = new MutagenEncodingWrapper(new UTF8Encoding(false, true));
    var read = new BinaryReadParameters
    {
        StringsParam = new StringsReadParameters
        {
            NonTranslatedEncodingOverride = utf8,
            NonLocalizedEncodingOverride = utf8,
        }
    };
    using var source = SkyrimMod.CreateFromBinaryOverlay(input, SkyrimRelease.SkyrimSE, read);
    var sourceKey = ModKey.FromNameAndExtension("RFAB.esp");
    var skyrimKey = ModKey.FromNameAndExtension("Skyrim.esm");
    var effectKey = new FormKey(sourceKey, 0x1124AF);
    var original = source.MagicEffects[effectKey];
    if (original.EditorID != effectEditorId || original.Conditions.Count != 0)
        throw new InvalidOperationException("Unexpected source magic effect.");

    var patch = new SkyrimMod(ModKey.FromNameAndExtension(patchName), SkyrimRelease.SkyrimSE);
    patch.ModHeader.Stats.Version = source.ModHeader.Stats.Version;
    patch.ModHeader.Author = "mod_fix";
    patch.ModHeader.Description = "RFAB: filter neutral recipients of the shock set's secondary lightning. Test candidate.";
    var effect = patch.MagicEffects.GetOrAddAsOverride(original);
    var condition = new IsHostileToActorConditionData
    {
        RunOnType = Condition.RunOnType.Subject,
    };
    condition.TargetNpc.Link.SetTo(new FormKey(skyrimKey, 0x14));
    effect.Conditions.Add(new ConditionFloat
    {
        CompareOperator = CompareOperator.EqualTo,
        ComparisonValue = 1f,
        Data = condition,
    });

    Directory.CreateDirectory(Path.GetDirectoryName(output)!);
    patch.WriteToBinary(output, new BinaryWriteParameters
    {
        Encodings = new EncodingBundle(utf8, utf8),
        MastersListOrdering = new MastersListOrderingByLoadOrder(
            source.ModHeader.MasterReferences.Select(m => m.Master).Append(source.ModKey)),
    });

    using var check = SkyrimMod.CreateFromBinaryOverlay(output, SkyrimRelease.SkyrimSE, read);
    var written = check.MagicEffects[effectKey];
    if (check.EnumerateMajorRecords().Count() != 1
        || written.Conditions.Count != 1
        || written.Conditions[0] is not IConditionFloatGetter c
        || c.CompareOperator != CompareOperator.EqualTo
        || c.ComparisonValue != 1f
        || c.Data is not IIsHostileToActorConditionDataGetter h
        || h.RunOnType != Condition.RunOnType.Subject
        || h.TargetNpc.Link.FormKey != new FormKey(skyrimKey, 0x14)
        || !check.ModHeader.MasterReferences.Select(m => m.Master)
            .SequenceEqual(new[] { skyrimKey, sourceKey }))
        throw new InvalidOperationException("Mutagen read-back validation failed.");
    if (Hash(input) != originalHash)
        throw new InvalidOperationException("Source hash changed during generation.");

    Console.WriteLine($"Created: {output}");
    Console.WriteLine($"Source SHA-256: {originalHash}");
    Console.WriteLine($"Patch SHA-256: {Hash(output)}");
    Console.WriteLine("One MGEF override; IsHostileToActor(PlayerRef) == 1, Subject. Game test pending.");
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.Message);
    return 1;
}

static string Hash(string path)
{
    using var stream = File.OpenRead(path);
    return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
}
