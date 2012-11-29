var numDbs = 2000;
var numOps = 100;

var complexDoc = {'product_name': 'Soap', 'weight': 22, 'weight_unit': 'kilogram', 'unique_url': 'http://amazon.com/soap22', 'categories': [{'title': 'cleaning', 'order': 29}, {'title': 'pets', 'order': 19}], 'reviews': [{'author': 'Whisper Jack','message': 'my dog is still dirty, but i`m clean'}, {'author': 'Happy Marry','message': 'my cat is never been this clean'}]};

var ops = [];

// Create databases, insert one document
// and prepare 2 operations to benchmark on that last document
for ( i=0; i<numDbs; i++ ) {
    var find_op =  {
        "op" : "findOne"
    };

    var update_op = {
        "op" : "update",
        "update" : { "$inc" : { "weight" : 1 } }
    };
    var coll = db.getSisterDB('boom-' + i)['boom'];
    // drop every database
    db.getSisterDB('boom-' + i).dropDatabase();

    find_op.ns = coll.toString();

    update_op.ns = coll.toString();

    // insert 1000 docs in each db
    complexDoc._id = new ObjectId();
    coll.insert(complexDoc);

    var query = { "_id" : complexDoc._id };
    find_op.query = query;
    ops.push(find_op);
    update_op.query = query;
    ops.push(update_op);
}

// remove randomly operations that will be benchmarked until only the numOps remain (ie. 100)
while (ops.length > numOps) {
    rnd = Math.floor(Math.random() * numDbs * 2);
    ops.splice(rnd,1);
}

// actual benchmark function
function bench1 () {
    for ( x = 1; x<=128; x*=2){
        res = benchRun( {
            parallel : x ,
            seconds : 5 ,
            ops : ops
        } );
        print( "threads: " + x + "\t queries/sec: " + res.query );
    }
}